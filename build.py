import os
import sys
import io
import re
import shutil
import json
import time
import unicodedata
import yaml
from datetime import datetime, timedelta, timezone
import fitz  # PyMuPDF
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.cloud import storage
from jinja2 import Environment, FileSystemLoader

# Stream stdout line-by-line so CI logs show progress live, instead of staying
# silent until a block buffer fills or the process exits — which previously hid
# where a slow/hung build was actually stuck.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# Configuration
# Checked in __main__ rather than raising here, so the module stays importable
# (e.g. by the tests) without a bucket configured.
BUCKET_NAME = os.environ.get('GCS_BUCKET')
BASE_URL = 'https://songbooks.ukuleletuesday.ie'
# Base URL for individual song chord sheets on the songs site. Changelog songs
# are linked here so readers can jump straight to a sheet that was added.
SONGS_SHEET_BASE_URL = 'https://ukuleletuesday.github.io/songs/sheets'
OUTPUT_DIR = 'public'
PREVIEW_DIR = os.path.join(OUTPUT_DIR, 'previews')
TEMPLATE_DIR = 'templates'
TEMPLATE_FILE = 'index.html.j2'
EDITIONS_FILE = 'editions.yml'

# Buy Me a Coffee data is cached between builds (persisted via actions/cache) so we
# hit the rate-limited API at most once per TTL instead of on every 15-min build.
# The two buckets are cached separately so a failure on one never stales the other.
CACHE_DIR = '.bmc-cache'
BMC_CACHE_TTL = timedelta(hours=24)
DEFAULT_STATS = {'total_amount': 912, 'supporter_count': 61, 'currency': '€'}
DEFAULT_SUBSCRIPTIONS = []
# Number of older changelog entries to list under the latest change in the
# "What's new" panel (the most recent change is always shown in full).
CHANGELOG_HISTORY_LIMIT = 10
# Public editions whose content changed within this window are listed in the
# main grid; older ones are tucked under the "Show all songbooks" expander.
# Pinned editions are always in the main grid regardless of age.
FEATURED_WINDOW_DAYS = 30
# Editions whose content changed within this window get an "Updated" badge.
RECENT_BADGE_DAYS = 7
# The visibility values latest.json / overrides may carry. Anything else
# (including a latest.json that predates the visibility field) is treated as
# 'unlisted': the book stays reachable at its /<edition>/ URL but unlisted.
VALID_VISIBILITIES = ('public', 'unlisted')

class _LoggingRetry(Retry):
    """A urllib3 Retry that announces each wait it takes.

    Retries — especially Retry-After sleeps on 429s — are otherwise silent, so a
    rate-limited request looks like a multi-minute hang with no explanation.
    This logs which status triggered the retry and how long we're about to wait.
    """

    def sleep(self, response=None):
        retry_after = None
        if response is not None and self.respect_retry_after_header:
            retry_after = self.get_retry_after(response)
        if retry_after:
            print(f"    BMC retry: status {response.status}, honoring Retry-After — sleeping {retry_after:.0f}s", flush=True)
        else:
            backoff = self.get_backoff_time()
            if backoff > 0:
                where = f"status {response.status}" if response is not None else "connection error"
                print(f"    BMC retry: {where} — backing off {backoff:.1f}s", flush=True)
        super().sleep(response)

def create_session_with_retry(max_retries=5, backoff_factor=1):
    """
    Creates a requests Session with retry configuration for 429 errors.
    
    Args:
        max_retries: Maximum number of retry attempts for 429 errors
        backoff_factor: Multiplier for exponential backoff (1 = 1s, 2s, 4s, 8s, 16s)
        
    Returns:
        requests.Session configured with retry adapter
    """
    retry = _LoggingRetry(
        total=max_retries,
        backoff_factor=backoff_factor,       # exponential backoff: 1s, 2s, 4s…
        # Don't auto-retry HTTP error statuses. BMC answers a 429 rate limit with
        # Retry-After: 3600 — not job-friendly — so retrying/honoring it would
        # block the build for up to an hour. We surface the 429 immediately and
        # bail to fallback values in the caller instead.
        status_forcelist=[],
        allowed_methods=['GET'],             # only retry transient connection errors
        respect_retry_after_header=False,
        raise_on_status=False,               # don't raise exceptions, return response
    )
    
    adapter = HTTPAdapter(max_retries=retry)
    
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session


def parse_timestamp(value):
    """Parses an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def get_overrides(path=EDITIONS_FILE):
    """Reads the optional per-edition overrides from editions.yml.

    The edition list itself comes from the bucket (see discover_editions);
    this file only exists to override an edition's publish metadata without
    waiting for a songbook-generator publish — e.g. to pull a book off the
    site in an emergency.

    Returns {edition_name: {'visibility': ..., 'pinned': ...}} with only the
    keys actually overridden. Missing file or empty overrides map -> {}.
    Invalid values are logged and ignored.
    """
    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

    overrides = {}
    for name, item in (config.get('overrides') or {}).items():
        if not isinstance(item, dict):
            print(f"  Ignoring invalid override for '{name}': {item!r}")
            continue
        entry = {}
        if 'visibility' in item:
            if item['visibility'] in VALID_VISIBILITIES:
                entry['visibility'] = item['visibility']
            else:
                print(f"  Ignoring invalid visibility override for '{name}': {item['visibility']!r}")
        if 'pinned' in item:
            entry['pinned'] = bool(item['pinned'])
        if entry:
            overrides[name] = entry
    return overrides

def list_edition_names(bucket):
    """Lists the top-level prefixes ("folders") of the bucket, one per edition.

    Whether a prefix is a real edition is decided later by whether it has a
    usable latest.json (see discover_editions).
    """
    iterator = bucket.client.list_blobs(bucket, prefix='', delimiter='/')
    prefixes = set()
    # prefixes only populate as the pages are consumed
    for page in iterator.pages:
        prefixes.update(page.prefixes)
    return sorted(name.rstrip('/') for name in prefixes)

def resolve_publish_meta(latest_info, override=None):
    """Resolves an edition's visibility/pinned with precedence:
    editions.yml override > latest.json > defaults.

    A latest.json without a valid visibility value predates the publish
    metadata (stale, never re-published since) and is treated as unlisted —
    such books stay reachable at their /<edition>/ URL but are not listed.
    """
    latest_info = latest_info or {}
    override = override or {}
    visibility = latest_info.get('visibility')
    if visibility not in VALID_VISIBILITIES:
        visibility = 'unlisted'
    meta = {
        'visibility': override.get('visibility', visibility),
        'pinned': bool(override.get('pinned', latest_info.get('pinned', False))),
    }
    return meta

def discover_editions(bucket, overrides=None):
    """Discovers the editions to display from the bucket contents.

    An edition is any top-level prefix with a latest.json naming a PDF;
    anything else (stray folders, half-published editions) is skipped with a
    log line. Returns [{'name', 'latest', 'visibility', 'pinned'}].
    """
    overrides = overrides or {}
    editions = []
    for name in list_edition_names(bucket):
        latest_info = get_latest_edition_info(bucket, name)
        if not latest_info or not latest_info.get('pdf_filename'):
            print(f"  Skipping '{name}': no usable latest.json")
            continue
        meta = resolve_publish_meta(latest_info, overrides.get(name))
        editions.append({'name': name, 'latest': latest_info, **meta})
    return editions

def get_latest_edition_info(bucket, edition_name):
    """Fetches and parses the latest.json for a given edition."""
    blob_name = f"{edition_name}/latest.json"
    blob = bucket.blob(blob_name)
    try:
        latest_url = f"https://storage.googleapis.com/{bucket.name}/{blob_name}"
        print(f"  Fetching latest.json from: {latest_url}")
        data = blob.download_as_text()
        return json.loads(data)
    except Exception as e:
        print(f"  Could not fetch or parse {blob_name}: {e}")
        return None

def get_edition_changes(bucket, edition_name):
    """Fetches and parses an edition's changes.json.

    changes.json is the append-only changelog history maintained by the
    songbook-generator: a dict with an 'entries' list ordered newest-first,
    each entry describing the songs added/removed in a publish.
    """
    blob_name = f"{edition_name}/changes.json"
    blob = bucket.blob(blob_name)
    try:
        changes_url = f"https://storage.googleapis.com/{bucket.name}/{blob_name}"
        print(f"  Fetching changes from: {changes_url}")
        data = blob.download_as_text()
        return json.loads(data)
    except Exception as e:
        print(f"  Could not fetch or parse changes {blob_name}: {e}")
        return None

def format_changelog_date(generated_at):
    """Formats an ISO 8601 timestamp into a short date like '9 Jun 2026'.

    Returns an empty string if the timestamp is missing or unparseable.
    """
    if not generated_at:
        return ''
    try:
        dt = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return ''
    return f"{dt.day} {dt:%b %Y}"

def song_sheet_url(name):
    """Builds the public chord-sheet URL for a changelog song entry.

    Songs appear in changes.json as "Title - Artist" strings; the songs site
    publishes each at /songs/sheets/<slug>/, where the slug is that string
    lowercased with accents stripped, apostrophes removed, and every run of
    other non-alphanumeric characters collapsed to a single hyphen — e.g.
    "Can't Get You Out of My Head - Kylie Minogue" becomes
    "cant-get-you-out-of-my-head-kylie-minogue".

    Returns None when the name yields an empty slug, so callers can fall back
    to plain text rather than linking to a broken URL.
    """
    # Strip accents (é -> e) and drop any remaining non-ASCII characters.
    ascii_name = (
        unicodedata.normalize('NFKD', name)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    # Remove apostrophes outright so "can't" -> "cant", not "can-t".
    ascii_name = ascii_name.replace("'", '')
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.lower()).strip('-')
    if not slug:
        return None
    return f"{SONGS_SHEET_BASE_URL}/{slug}/"

def _changelog_song(name):
    """Shapes one changelog song into a display name and its sheet URL (which
    may be None when no valid slug can be derived)."""
    return {'name': name, 'url': song_sheet_url(name)}

def _changelog_entry(entry):
    """Shapes one changes.json entry for display: a date plus the song lists
    added and removed, each song carrying its name and chord-sheet URL."""
    return {
        'date': format_changelog_date(entry.get('generated_at')),
        'added': [_changelog_song(s) for s in entry.get('added', [])],
        'removed': [_changelog_song(s) for s in entry.get('removed', [])],
    }

def build_changelog(changes, history_limit=CHANGELOG_HISTORY_LIMIT):
    """Builds the "What's new" panel data from an edition's changes.json.

    Surfaces the most recent change followed by a short history of earlier
    changes, each shaped identically (a date plus the songs added/removed). The
    'entries' in `changes` are expected newest-first, as published by the
    generator.

    Returns a dict shaped like::

        {
            'latest': {'date': '9 Jun 2026', 'added': [...], 'removed': [...]},
            'earlier': [{'date': '2 Jun 2026', 'added': [...], 'removed': [...]}, ...],
        }

    or None when there are no entries with any additions or removals.
    """
    if not changes:
        return None

    entries = [
        entry for entry in changes.get('entries', [])
        if entry.get('added') or entry.get('removed')
    ]
    if not entries:
        return None

    return {
        'latest': _changelog_entry(entries[0]),
        'earlier': [_changelog_entry(entry) for entry in entries[1:1 + history_limit]],
    }

def content_updated_at(changes, latest_info):
    """When this edition's content last actually changed.

    The cron-regenerated books get a fresh latest.json (and generated_at)
    every run even when nothing changed, so ordering by generated_at would
    show them as perpetually new. The newest changes.json entry with songs
    added or removed is the real content-change signal; generated_at is only
    the fallback for editions without any such entry.
    """
    for entry in (changes or {}).get('entries', []):
        if entry.get('added') or entry.get('removed'):
            dt = parse_timestamp(entry.get('generated_at'))
            if dt:
                return dt
    return parse_timestamp((latest_info or {}).get('generated_at'))

def sort_editions(editions):
    """Pinned editions first, then most recently updated, then by name."""
    def key(edition):
        dt = edition.get('updated_dt')
        return (
            not edition.get('pinned'),
            dt is None,
            -dt.timestamp() if dt else 0,
            edition['edition_name'],
        )
    return sorted(editions, key=key)

def partition_editions(editions, now=None):
    """Splits public editions into (featured, more), each sorted.

    Featured — the main grid — is every pinned edition plus any edition whose
    content changed in the last FEATURED_WINDOW_DAYS. The rest go under the
    "Show all songbooks" expander.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FEATURED_WINDOW_DAYS)
    featured, more = [], []
    for edition in sort_editions(editions):
        dt = edition.get('updated_dt')
        if edition.get('pinned') or (dt and dt >= cutoff):
            featured.append(edition)
        else:
            more.append(edition)
    return featured, more

def _response_error_snippet(response, limit=500):
    """Return a trimmed snippet of a response body for diagnostic logging.

    Buy Me a Coffee returns a JSON error body on failures, while infrastructure
    errors (e.g. a 502 from the gateway) return an HTML page. Logging a snippet
    of either lets us tell those cases apart from the build logs instead of
    only seeing a bare status code.
    """
    body = (response.text or '').strip()
    if not body:
        return '(empty response body)'
    if len(body) > limit:
        return body[:limit] + '... (truncated)'
    return body

def _auth_hint(response):
    """Flag the most common cause of a failed call: an expired/revoked token
    returns 401/403, or — without an Accept: application/json header — the API
    redirects to its login page instead of returning a clean 401."""
    if response.status_code in (401, 403) or response.is_redirect:
        return " Token may be expired or revoked — regenerate BUYMEACOFFEE_API_TOKEN."
    return ""

def _rate_limit_hint(response):
    """For a 429, surface the Retry-After we're deliberately not honoring."""
    if response.status_code == 429:
        retry_after = response.headers.get('Retry-After')
        return f" Rate-limited; Retry-After={retry_after}s is not job-friendly, bailing to fallback."
    return ""

def get_buymeacoffee_stats():
    """Fetch supporter statistics from the Buy Me a Coffee API with pagination.

    Returns a {'total_amount', 'supporter_count', 'currency'} dict on success, or
    None on any failure so the caller can choose between a cached or default value.
    """
    # Check if API token is available
    api_token = os.environ.get('BUYMEACOFFEE_API_TOKEN')
    if not api_token:
        print("  No Buy Me a Coffee API token found", flush=True)
        return None

    # Tracked out here so the error handlers below can report which page failed.
    page = 1
    try:
        # Create session with retry configuration
        session = create_session_with_retry()
        
        # Make API request to Buy Me a Coffee with pagination
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json',
        }

        all_supporters = []
        page_size = 50  # Larger page size to get more results per request
        total_pages = 1  # Assume at least one page
        start_time = time.monotonic()

        while True:
            params = {
                'page': page,
                'per_page': page_size
            }

            # Logged and flushed *before* the request so a hang or timeout shows
            # exactly which page stalled instead of the log going silent.
            print(f"  Requesting supporters page {page}/{total_pages} (per_page={page_size}, timeout=10s)...", flush=True)

            try:
                response = session.get(
                    'https://developers.buymeacoffee.com/api/v1/supporters',
                    headers=headers,
                    params=params,
                    timeout=10,
                    allow_redirects=False
                )
            except requests.Timeout:
                print(f"  Buy Me a Coffee API timed out after 10s on page {page}", flush=True)
                return None

            if response.status_code != 200:
                print(f"  Buy Me a Coffee API returned status {response.status_code} on page {page}.{_auth_hint(response)}{_rate_limit_hint(response)} Response body: {_response_error_snippet(response)}", flush=True)
                return None

            data = response.json()

            if page == 1:
                # On the first request, get the total number of pages
                total_pages = data.get('last_page', 1)

            supporters = data.get('data', [])
            all_supporters.extend(supporters)
            print(f"    page {page}/{total_pages}: received {len(supporters)} supporters (running total {len(all_supporters)})", flush=True)

            # Stop on an empty page or when the API reports no further pages.
            if not supporters or data.get('next_page_url') is None:
                break

            page += 1

            # Safety break to avoid infinite loops
            if page > 100:
                print(f"  Warning: Stopped at page {page} to avoid infinite loop", flush=True)
                break

        # Calculate totals from all supporters
        total_amount = 0
        supporter_count = len(all_supporters)

        for supporter in all_supporters:
            # Convert API response values to numbers to handle string responses
            try:
                coffees = float(supporter.get('support_coffees', 0))
                price = float(supporter.get('support_coffee_price', 3))
                amount = coffees * price
                total_amount += amount
            except (ValueError, TypeError):
                # Skip this supporter if values can't be converted to numbers
                continue

        elapsed = time.monotonic() - start_time
        print(f"  Fetched Buy Me a Coffee stats: €{int(total_amount)} from {supporter_count} supporters across {page} page(s) in {elapsed:.1f}s", flush=True)

        return {
            'total_amount': int(total_amount),
            'supporter_count': supporter_count,
            'currency': '€'
        }

    except requests.RequestException as e:
        print(f"  Error fetching Buy Me a Coffee stats on page {page}: {e}", flush=True)
        return None
    except Exception as e:
        print(f"  Unexpected error with Buy Me a Coffee API on page {page}: {e}", flush=True)
        return None

def get_buymeacoffee_subscriptions():
    """Fetch active monthly subscriptions from the Buy Me a Coffee API.

    Returns a list of supporter names on success (possibly empty), or None on any
    failure so the caller can fall back to a cached or default value.
    """
    # Check if API token is available
    api_token = os.environ.get('BUYMEACOFFEE_API_TOKEN')
    if not api_token:
        print("  No Buy Me a Coffee API token found", flush=True)
        return None

    # Tracked out here so the error handlers below can report which page failed.
    page = 1
    try:
        # Create session with retry configuration
        session = create_session_with_retry()
        
        # Make API request to Buy Me a Coffee subscriptions endpoint
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json',
        }

        all_subscriptions = []
        page_size = 50  # Larger page size to get more results per request
        total_pages = 1  # Assume at least one page
        start_time = time.monotonic()

        while True:
            params = {
                'page': page,
                'per_page': page_size,
                'status': 'active'
            }

            # Logged and flushed *before* the request so a hang or timeout shows
            # exactly which page stalled instead of the log going silent.
            print(f"  Requesting subscriptions page {page}/{total_pages} (per_page={page_size}, timeout=10s)...", flush=True)

            try:
                response = session.get(
                    'https://developers.buymeacoffee.com/api/v1/subscriptions',
                    headers=headers,
                    params=params,
                    timeout=10,
                    allow_redirects=False
                )
            except requests.Timeout:
                print(f"  Buy Me a Coffee subscriptions API timed out after 10s on page {page}", flush=True)
                return None

            if response.status_code != 200:
                print(f"  Buy Me a Coffee subscriptions API returned status {response.status_code} on page {page}.{_auth_hint(response)}{_rate_limit_hint(response)} Response body: {_response_error_snippet(response)}", flush=True)
                return None

            data = response.json()

            if page == 1:
                # On the first request, get the total number of pages
                total_pages = data.get('last_page', 1)

            subscriptions = data.get('data', [])
            all_subscriptions.extend(subscriptions)
            print(f"    page {page}/{total_pages}: received {len(subscriptions)} subscriptions (running total {len(all_subscriptions)})", flush=True)

            # Stop on an empty page or when the API reports no further pages.
            if not subscriptions or data.get('next_page_url') is None:
                break

            page += 1

            # Safety break to avoid infinite loops
            if page > 100:
                print(f"  Warning: Stopped at page {page} to avoid infinite loop", flush=True)
                break

        # Extract supporter names from subscriptions
        supporter_names = []
        for sub in all_subscriptions:
            name = (sub.get('payer_name') or '').strip()
            if name:
                supporter_names.append(name)

        elapsed = time.monotonic() - start_time
        print(f"  Fetched {len(supporter_names)} monthly supporters from Buy Me a Coffee across {page} page(s) in {elapsed:.1f}s", flush=True)

        return supporter_names

    except requests.RequestException as e:
        print(f"  Error fetching Buy Me a Coffee subscriptions on page {page}: {e}", flush=True)
        return None
    except Exception as e:
        print(f"  Unexpected error with Buy Me a Coffee subscriptions API on page {page}: {e}", flush=True)
        return None

def _cache_path(name):
    return os.path.join(CACHE_DIR, f'{name}.json')

def _read_cache(name):
    """Return the cached {'fetched_at', 'data'} entry, or None if missing/unreadable."""
    try:
        with open(_cache_path(name)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

def _write_cache(name, data):
    """Persist `data` under `name` with the current UTC timestamp."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(name), 'w') as f:
        json.dump({'fetched_at': datetime.now(timezone.utc).isoformat(), 'data': data}, f, indent=2)

def _cache_age(entry):
    """Age of a cache entry; treat a missing/unparseable timestamp as infinitely old."""
    try:
        fetched_at = datetime.fromisoformat(entry['fetched_at'])
    except (KeyError, TypeError, ValueError):
        return timedelta.max
    return datetime.now(timezone.utc) - fetched_at

def _fetch_with_cache(name, fetch_fn, default, label, ttl=BMC_CACHE_TTL):
    """Return cached data when it's within `ttl`, otherwise fetch fresh.

    Each bucket (stats, subscriptions) is cached independently. On a failed fetch
    (fetch_fn returns None) we reuse the last cached value, falling back to
    `default` only when there is no cache at all.
    """
    entry = _read_cache(name)
    if entry is not None and _cache_age(entry) < ttl:
        print(f"  Using cached {label} (fetched {entry['fetched_at']}) — skipping BMC call", flush=True)
        return entry['data']

    data = fetch_fn()
    if data is not None:
        _write_cache(name, data)
        return data

    if entry is not None:
        print(f"  {label} fetch failed; reusing last cached value from {entry['fetched_at']}", flush=True)
        return entry['data']

    print(f"  {label} fetch failed and no cache available; using built-in default", flush=True)
    return default

def download_pdf_from_url(url):
    """Downloads a PDF from a URL and returns the bytes."""
    from urllib.request import urlopen
    with urlopen(url) as response:
        return response.read()

def process_pdf_url(edition_name, pdf_url, preview_path):
    """
    Downloads a PDF from URL, saves the first page as a PNG image,
    and returns its metadata.
    """
    print(f"  Processing {edition_name}...")
    pdf_data = download_pdf_from_url(pdf_url)
    pdf_document = fitz.open(stream=pdf_data, filetype="pdf")

    # Generate preview image
    if len(pdf_document) > 0:
        first_page = pdf_document.load_page(0)
        pix = first_page.get_pixmap(dpi=150, alpha=True)
        pix.save(preview_path)

    # Extract metadata, fallback to edition name for title
    metadata = pdf_document.metadata
    title = metadata.get('title') or edition_name
    subject = metadata.get('subject', '') # Default to empty string if no subject

    return {'title': title, 'subject': subject}

def render_index(file_list, more_files=None, last_updated=None, base_url=None, supporter_stats=None, monthly_supporters=None):
    """Renders the HTML index page.

    `file_list` fills the main grid; `more_files` go under the collapsed
    "Show all songbooks" section (omitted entirely when empty).
    """
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(
        files=file_list,
        more_files=more_files or [],
        last_updated=last_updated,
        base_url=base_url,
        supporter_stats=supporter_stats,
        monthly_supporters=monthly_supporters or [],
        site_title="Ukulele Tuesday Songbooks",
        site_description="Download the Ukulele Tuesday songbooks and play along with us every week."
    )

def write_redirects(editions, output_dir=OUTPUT_DIR):
    """Writes a /<edition>/ redirect page for every edition.

    Unlisted editions get one too: an unlisted book is off the listing but
    stays reachable (and shareable) at its stable URL.
    """
    count = 0
    for songbook in editions:
        redirect_dir = os.path.join(output_dir, songbook['edition_name'])
        os.makedirs(redirect_dir, exist_ok=True)

        # Create a simple HTML file with a meta refresh tag for redirection
        redirect_html = f"""<!DOCTYPE html>
<html>
<head>
<title>Redirecting to {songbook['title']}</title>
<link rel="canonical" href="{songbook['url']}" />
<meta http-equiv="refresh" content="0; url={songbook['url']}">
<script>window.location.replace("{songbook['url']}");</script>
</head>
<body>
<p>If you are not redirected, <a href="{songbook['url']}">click here to view the songbook</a>.</p>
</body>
</html>"""

        with open(os.path.join(redirect_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(redirect_html)
        count += 1
    return count

def write_output(html):
    """Writes the rendered HTML to the output directory."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

    # Copy assets directory
    assets_src = 'assets'
    assets_dest = os.path.join(OUTPUT_DIR, 'assets')
    if os.path.exists(assets_src):
        if os.path.exists(assets_dest):
            shutil.rmtree(assets_dest)
        shutil.copytree(assets_src, assets_dest)

if __name__ == '__main__':
    if not BUCKET_NAME:
        sys.exit("GCS_BUCKET environment variable is not set")

    overrides = get_overrides()
    if overrides:
        print(f"Applying {len(overrides)} override(s) from {EDITIONS_FILE}: {', '.join(sorted(overrides))}")

    storage_client = storage.Client.create_anonymous_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    print(f"Discovering editions in bucket {BUCKET_NAME}...")
    editions = discover_editions(bucket, overrides)
    print(f"Discovered {len(editions)} editions")

    os.makedirs(PREVIEW_DIR, exist_ok=True)

    # Buy Me a Coffee supporter stats — cached between builds (see _fetch_with_cache)
    print("Fetching Buy Me a Coffee supporter statistics...")
    supporter_stats = _fetch_with_cache('stats', get_buymeacoffee_stats, DEFAULT_STATS, 'supporter stats')

    # Buy Me a Coffee monthly supporters — cached separately
    print("Fetching Buy Me a Coffee monthly supporters...")
    monthly_supporters = _fetch_with_cache('subscriptions', get_buymeacoffee_subscriptions, DEFAULT_SUBSCRIPTIONS, 'monthly supporters')

    now = datetime.now(timezone.utc)
    latest_update_time = None
    all_songbooks = []

    for edition in editions:
        edition_name = edition['name']
        latest_info = edition['latest']
        print(f"Processing edition: {edition_name} ({edition['visibility']}{', pinned' if edition['pinned'] else ''})")

        changes = get_edition_changes(bucket, edition_name)
        changelog = build_changelog(changes)
        updated_dt = content_updated_at(changes, latest_info)

        # The footer's site-wide "Last updated" reflects listed books only —
        # an unlisted edition shouldn't bump a timestamp nobody can see.
        if edition['visibility'] == 'public':
            generated_dt = parse_timestamp(latest_info.get('generated_at'))
            if generated_dt and (latest_update_time is None or generated_dt > latest_update_time):
                latest_update_time = generated_dt

        pdf_filename = latest_info['pdf_filename']
        pdf_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{edition_name}/{pdf_filename}"
        print(f"  Using PDF URL: {pdf_url}")

        preview_filename = f"{edition_name}.png"
        preview_path_abs = os.path.join(PREVIEW_DIR, preview_filename)

        metadata = process_pdf_url(edition_name, pdf_url, preview_path_abs)

        edition_data = {
            'edition_name': edition_name,
            'title': metadata['title'],
            'subject': metadata['subject'],
            'url': pdf_url,
            'preview_image': f'previews/{preview_filename}',
            'filename': pdf_filename,
            'visibility': edition['visibility'],
            'pinned': edition['pinned'],
            'updated_dt': updated_dt,
            'updated_at': updated_dt.isoformat() if updated_dt else None,
            'updated_display': format_changelog_date(updated_dt.isoformat()) if updated_dt else '',
            'recently_updated': bool(updated_dt and now - updated_dt <= timedelta(days=RECENT_BADGE_DAYS)),
        }

        if changelog:
            edition_data['changelog'] = changelog

        all_songbooks.append(edition_data)

    public_songbooks = [s for s in all_songbooks if s['visibility'] == 'public']
    featured, more = partition_editions(public_songbooks, now=now)

    last_updated_iso = latest_update_time.isoformat() if latest_update_time else None
    html = render_index(featured, more_files=more, last_updated=last_updated_iso, base_url=BASE_URL, supporter_stats=supporter_stats, monthly_supporters=monthly_supporters)
    write_output(html)
    print(f"Generated {len(featured)} featured + {len(more)} more songbooks → {OUTPUT_DIR}/index.html")

    # Generate redirects for each edition (both public and unlisted)
    print("Generating redirects for each edition...")
    redirect_count = write_redirects(all_songbooks)
    if redirect_count > 0:
        print(f"Generated {redirect_count} redirects.")
