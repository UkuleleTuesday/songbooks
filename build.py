import os
import io
import shutil
import json
import fitz  # PyMuPDF
import requests
from google.cloud import storage
from jinja2 import Environment, FileSystemLoader

# Configuration
BUCKET_NAME = os.environ['GCS_BUCKET']
BASE_URL = 'https://songbooks.ukuleletuesday.ie'
OUTPUT_DIR = 'public'
PREVIEW_DIR = os.path.join(OUTPUT_DIR, 'previews')
TEMPLATE_DIR = 'templates'
TEMPLATE_FILE = 'index.html.j2'

def get_manifest(bucket_name):
    """Downloads and parses the manifest.json file from the bucket."""
    client = storage.Client.create_anonymous_client()
    bucket = client.bucket(bucket_name)
    manifest_blob = bucket.blob('manifest.json')
    manifest_data = manifest_blob.download_as_text()
    return json.loads(manifest_data)

def get_buymeacoffee_stats():
    """Fetch supporter statistics from Buy Me a Coffee API with pagination."""
    # Fallback values in case API fails
    fallback_stats = {
        'total_amount': 912,
        'supporter_count': 61,
        'currency': '€'
    }
    
    # Check if API token is available
    api_token = os.environ.get('BUYMEACOFFEE_API_TOKEN')
    if not api_token:
        print("  No Buy Me a Coffee API token found, using fallback values")
        return fallback_stats
    
    try:
        # Make API request to Buy Me a Coffee with pagination
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        
        all_supporters = []
        page = 1
        page_size = 50  # Larger page size to get more results per request
        
        while True:
            params = {
                'page': page,
                'per_page': page_size
            }
            
            response = requests.get(
                'https://developers.buymeacoffee.com/api/v1/supporters',
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"  Buy Me a Coffee API returned status {response.status_code} on page {page}, using fallback values")
                return fallback_stats
            
            data = response.json()
            supporters = data.get('data', [])
            
            if not supporters:
                # No more supporters to fetch
                break
                
            all_supporters.extend(supporters)
            
            # Check if we've reached the last page
            if data.get('next_page_url') is None:
                break
                
            page += 1
            
            # Safety break to avoid infinite loops
            if page > 100:
                print(f"  Warning: Stopped at page {page} to avoid infinite loop")
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
        
        print(f"  Fetched Buy Me a Coffee stats: €{total_amount} from {supporter_count} supporters ({page} pages)")
        
        return {
            'total_amount': int(total_amount),
            'supporter_count': supporter_count,
            'currency': '€'
        }
            
    except requests.RequestException as e:
        print(f"  Error fetching Buy Me a Coffee stats: {e}, using fallback values")
        return fallback_stats
    except Exception as e:
        print(f"  Unexpected error with Buy Me a Coffee API: {e}, using fallback values")
        return fallback_stats

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

def render_index(file_list, last_updated=None, base_url=None, supporter_stats=None):
    """Renders the HTML index page."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(
        files=file_list, 
        last_updated=last_updated, 
        base_url=base_url,
        supporter_stats=supporter_stats
    )

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
    print(f"Fetching songbook manifest from GCS bucket: {BUCKET_NAME}")
    manifest = get_manifest(BUCKET_NAME)
    songbooks = []
    
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    last_updated = manifest.get('last_updated_utc')
    
    # Fetch Buy Me a Coffee supporter statistics
    print("Fetching Buy Me a Coffee supporter statistics...")
    supporter_stats = get_buymeacoffee_stats()

    for edition_name, edition_info in manifest['editions'].items():
        preview_filename = f"{edition_name}.png"
        preview_path_abs = os.path.join(PREVIEW_DIR, preview_filename)
        
        metadata = process_pdf_url(edition_name, edition_info['url'], preview_path_abs)

        songbooks.append({
            'title': metadata['title'],
            'subject': metadata['subject'],
            'url': edition_info['url'],
            'preview_image': f'previews/{preview_filename}'
        })

    html = render_index(songbooks, last_updated=last_updated, base_url=BASE_URL, supporter_stats=supporter_stats)
    write_output(html)
    print(f"Generated {len(songbooks)} songbooks → {OUTPUT_DIR}/index.html")
