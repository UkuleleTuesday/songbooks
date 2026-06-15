#!/usr/bin/env python3
"""Test script for build functionality."""

import os
import json
import pytest
import requests_mock

import yaml
from unittest.mock import MagicMock

# Import functions from build.py for testing
from build import get_buymeacoffee_stats, get_buymeacoffee_subscriptions, render_index, get_editions_config, get_latest_edition_info, get_edition_manifest, create_session_with_retry, get_edition_changes, build_changelog, format_changelog_date


@pytest.fixture
def test_env():
    """Test environment variables fixture."""
    return {
        'GCS_BUCKET': 'test-bucket',
        'BUYMEACOFFEE_API_TOKEN': 'test-token'
    }




@pytest.fixture
def sample_files():
    """Sample songbook files fixture."""
    return [
        {
            'title': 'Test Songbook',
            'subject': 'Folk Songs',
            'url': 'https://example.com/test.pdf',
            'preview_image': 'previews/test.png'
        }
    ]


@pytest.fixture
def sample_supporter_stats():
    """Sample supporter statistics fixture."""
    return {
        'total_amount': 500,
        'supporter_count': 25,
        'currency': '€'
    }

def test_get_buymeacoffee_stats_pagination(requests_mock):
    """Test Buy Me a Coffee API pagination."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API responses for multiple pages
    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    
    # Page 1 - full page (50 supporters)
    page1_data = {
        'data': [
            {'support_coffees': '5', 'support_coffee_price': '3'},
            {'support_coffees': '2', 'support_coffee_price': '5'},
        ] * 25,  # 50 supporters total (25 * 2)
        'last_page': 2,
        'next_page_url': f'{base_url}?page=2'
    }
    requests_mock.get(
        f'{base_url}?page=1&per_page=50',
        json=page1_data,
        status_code=200
    )
    
    # Page 2 - partial page (indicates end)
    page2_data = {
        'data': [
            {'support_coffees': '10', 'support_coffee_price': '3'},
            {'support_coffees': '1', 'support_coffee_price': '4'},
        ],
        'last_page': 2,
        'next_page_url': None
    }
    requests_mock.get(
        f'{base_url}?page=2&per_page=50',
        json=page2_data,
        status_code=200
    )
    
    try:
        result = get_buymeacoffee_stats()
        
        # Verify pagination worked
        assert len(requests_mock.request_history) == 2
        
        # Check first request parameters
        first_request = requests_mock.request_history[0]
        assert 'page=1' in first_request.url
        assert 'per_page=50' in first_request.url
        
        # Check second request parameters  
        second_request = requests_mock.request_history[1]
        assert 'page=2' in second_request.url
        assert 'per_page=50' in second_request.url
        
        # Verify calculations
        # Page 1: 25 * (5*3 + 2*5) = 25 * 25 = 625
        # Page 2: 10*3 + 1*4 = 34
        # Total: 625 + 34 = 659
        assert result['total_amount'] == 659
        assert result['supporter_count'] == 52
        assert result['currency'] == '€'
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_get_buymeacoffee_stats_api_error(requests_mock):
    """Test Buy Me a Coffee API error handling."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API to raise an exception
    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    requests_mock.get(
        f'{base_url}?page=1&per_page=50',
        exc=Exception("Network error")
    )
    
    try:
        result = get_buymeacoffee_stats()
        
        # Should return fallback values
        assert result['total_amount'] == 912
        assert result['supporter_count'] == 61
        assert result['currency'] == '€'
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_get_buymeacoffee_stats_no_token():
    """Test Buy Me a Coffee when no API token is provided."""
    # Ensure no token is set
    if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
        del os.environ['BUYMEACOFFEE_API_TOKEN']
    
    result = get_buymeacoffee_stats()
    
    # Should return fallback values
    assert result['total_amount'] == 912
    assert result['supporter_count'] == 61
    assert result['currency'] == '€'

def test_get_buymeacoffee_stats_invalid_data(requests_mock):
    """Test Buy Me a Coffee API with invalid data types."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API response with invalid data
    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    invalid_data = {
        'data': [
            {'support_coffees': 'invalid', 'support_coffee_price': '3'},
            {'support_coffees': '2', 'support_coffee_price': 'also_invalid'},
            {'support_coffees': '5', 'support_coffee_price': '4'},  # Valid entry
        ]
    }
    requests_mock.get(
        f'{base_url}?page=1&per_page=50',
        json=invalid_data,
        status_code=200
    )
    
    try:
        result = get_buymeacoffee_stats()
        
        # Should only count the valid entry: 5 * 4 = 20
        assert result['total_amount'] == 20
        assert result['supporter_count'] == 3  # All entries counted for supporter count
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_render_index(sample_files, sample_supporter_stats):
    """Test HTML template rendering."""
    # Render template
    html = render_index(
        sample_files, 
        last_updated='2024-01-01T12:00:00Z',
        base_url='https://test.example.com',
        supporter_stats=sample_supporter_stats
    )
    
    # Basic checks
    assert 'Test Songbook' in html
    assert 'Folk Songs' in html
    assert '€500' in html
    assert '25 supporters' in html
    assert '<!DOCTYPE html' in html
    
    # Check that email link is replaced with contact form link
    assert 'mailto:contact@ukuleletuesday.ie' not in html
    assert 'https://www.ukuleletuesday.ie/contact-us/' in html

def test_get_editions_config(monkeypatch):
    """Test reading the editions YAML config."""
    mock_yaml_content = {
        'editions': [
            {'name': 'current', 'show_changelog': True},
            {'name': 'complete'},
            {'name': 'wip', 'hidden': True},
            {'name': 'archive', 'show_changelog': False},
        ]
    }
    # Use monkeypatch to mock open() and yaml.safe_load()
    monkeypatch.setattr('builtins.open', lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr('build.yaml.safe_load', lambda *args: mock_yaml_content)

    editions = get_editions_config()
    # show_changelog defaults to True; it can be explicitly suppressed per edition.
    assert editions == [
        {'name': 'current', 'hidden': False, 'show_changelog': True},
        {'name': 'complete', 'hidden': False, 'show_changelog': True},
        {'name': 'wip', 'hidden': True, 'show_changelog': True},
        {'name': 'archive', 'hidden': False, 'show_changelog': False},
    ]

def test_get_latest_edition_info():
    """Test fetching and parsing latest.json from a mock GCS bucket."""
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    
    # Mock successful fetch
    latest_json_content = json.dumps({
        "pdf_filename": "songbook-current.pdf",
        "manifest_filename": "songbook-current.manifest.json"
    })
    mock_blob.download_as_text.return_value = latest_json_content
    mock_bucket.blob.return_value = mock_blob
    
    info = get_latest_edition_info(mock_bucket, 'current')
    assert info['pdf_filename'] == 'songbook-current.pdf'
    
    # Mock failed fetch (e.g., blob not found)
    mock_blob.download_as_text.side_effect = Exception("Not Found")
    info = get_latest_edition_info(mock_bucket, 'non-existent')
    assert info is None

def test_get_edition_manifest():
    """Test fetching and parsing an edition's manifest."""
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    # Mock successful fetch
    manifest_content = json.dumps({
        "generated_at": "2024-01-01T12:00:00Z"
    })
    mock_blob.download_as_text.return_value = manifest_content
    mock_bucket.blob.return_value = mock_blob

    manifest = get_edition_manifest(mock_bucket, 'current', 'manifest.json')
    assert manifest['generated_at'] == "2024-01-01T12:00:00Z"

    # Mock failed fetch
    mock_blob.download_as_text.side_effect = Exception("Not Found")
    manifest = get_edition_manifest(mock_bucket, 'current', 'manifest.json')
    assert manifest is None

def test_get_buymeacoffee_subscriptions_pagination(requests_mock):
    """Test Buy Me a Coffee subscriptions API pagination."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API responses for multiple pages
    base_url = 'https://developers.buymeacoffee.com/api/v1/subscriptions'
    
    # Page 1 - full page
    page1_data = {
        'data': [
            {'payer_name': 'John Doe', 'subscription_is_cancelled': None},
            {'payer_name': 'Jane Smith', 'subscription_is_cancelled': None},
            {'payer_name': 'Bob Wilson', 'subscription_is_cancelled': None},
        ],
        'last_page': 2,
        'next_page_url': f'{base_url}?page=2'
    }
    requests_mock.get(
        f'{base_url}?page=1&per_page=50&status=active',
        json=page1_data,
        status_code=200
    )
    
    # Page 2 - partial page
    page2_data = {
        'data': [
            {'payer_name': 'Alice Brown', 'subscription_is_cancelled': None},
        ],
        'last_page': 2,
        'next_page_url': None
    }
    requests_mock.get(
        f'{base_url}?page=2&per_page=50&status=active',
        json=page2_data,
        status_code=200
    )
    
    try:
        result = get_buymeacoffee_subscriptions()
        
        # Verify pagination worked
        assert len(requests_mock.request_history) == 2
        
        # Verify all names are present
        assert len(result) == 4
        assert 'John Doe' in result
        assert 'Jane Smith' in result
        assert 'Bob Wilson' in result
        assert 'Alice Brown' in result
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_get_buymeacoffee_subscriptions_no_token():
    """Test subscriptions API when no API token is provided."""
    # Ensure no token is set
    if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
        del os.environ['BUYMEACOFFEE_API_TOKEN']
    
    result = get_buymeacoffee_subscriptions()
    
    # Should return empty list
    assert result == []

def test_get_buymeacoffee_subscriptions_api_error(requests_mock):
    """Test subscriptions API error handling."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API to raise an exception
    base_url = 'https://developers.buymeacoffee.com/api/v1/subscriptions'
    requests_mock.get(
        f'{base_url}?page=1&per_page=50&status=active',
        exc=Exception("Network error")
    )
    
    try:
        result = get_buymeacoffee_subscriptions()
        
        # Should return empty list
        assert result == []
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_get_buymeacoffee_subscriptions_empty_names(requests_mock):
    """Test subscriptions API with empty names."""
    # Set environment variable for this test
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    # Mock API response with empty and valid names
    base_url = 'https://developers.buymeacoffee.com/api/v1/subscriptions'
    test_data = {
        'data': [
            {'payer_name': 'Valid Name', 'subscription_is_cancelled': None},
            {'payer_name': '', 'subscription_is_cancelled': None},
            {'payer_name': '   ', 'subscription_is_cancelled': None},
            {'payer_name': None, 'subscription_is_cancelled': None},  # None value
            {'subscription_is_cancelled': None},  # No payer_name field
        ],
        'next_page_url': None
    }
    requests_mock.get(
        f'{base_url}?page=1&per_page=50&status=active',
        json=test_data,
        status_code=200
    )
    
    try:
        result = get_buymeacoffee_subscriptions()
        
        # Should only include valid name
        assert len(result) == 1
        assert result[0] == 'Valid Name'
    finally:
        # Clean up environment variable
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']

def test_render_index_with_monthly_supporters(sample_files, sample_supporter_stats):
    """Test HTML template rendering with monthly supporters."""
    monthly_supporters = ['John Doe', 'Jane Smith', 'Bob Wilson']
    
    # Render template
    html = render_index(
        sample_files, 
        last_updated='2024-01-01T12:00:00Z',
        base_url='https://test.example.com',
        supporter_stats=sample_supporter_stats,
        monthly_supporters=monthly_supporters
    )
    
    # Check that monthly supporters section is present
    assert 'Special thanks to our monthly supporters:' in html
    assert 'John Doe' in html
    assert 'Jane Smith' in html
    assert 'Bob Wilson' in html

def test_get_edition_changes():
    """Test fetching and parsing an edition's changes.json."""
    mock_bucket = MagicMock()
    mock_bucket.name = 'test-bucket'
    mock_blob = MagicMock()

    changes_content = json.dumps({
        'edition': 'current',
        'entries': [
            {'generated_at': '2026-06-09T10:48:10+00:00', 'added': ['A - B'], 'removed': []},
        ],
    })
    mock_blob.download_as_text.return_value = changes_content
    mock_bucket.blob.return_value = mock_blob

    changes = get_edition_changes(mock_bucket, 'current')
    assert changes['edition'] == 'current'
    assert len(changes['entries']) == 1

    # Verify it fetches the expected blob path.
    mock_bucket.blob.assert_called_with('current/changes.json')

    # Mock failed fetch (e.g., blob not found)
    mock_blob.download_as_text.side_effect = Exception("Not Found")
    assert get_edition_changes(mock_bucket, 'current') is None


def test_format_changelog_date():
    """Test formatting an ISO timestamp into a short date."""
    assert format_changelog_date('2026-06-09T10:48:10.406245+00:00') == '9 Jun 2026'
    assert format_changelog_date('2026-12-25T00:00:00Z') == '25 Dec 2026'
    # Missing or unparseable timestamps fall back to an empty string.
    assert format_changelog_date(None) == ''
    assert format_changelog_date('') == ''
    assert format_changelog_date('not-a-date') == ''


def test_build_changelog():
    """Test building the 'What's new' panel data from changes.json."""
    changes = {
        'edition': 'current',
        'entries': [
            {
                'generated_at': '2026-06-09T10:48:10+00:00',
                'added': ['New Song - Artist A', 'Another One - Artist B'],
                'removed': ['Old Song - Artist C'],
                'added_count': 2,
                'removed_count': 1,
            },
            {
                'generated_at': '2026-06-02T15:23:23+00:00',
                'added': ['Hey Jude - The Beatles'],
                'removed': [],
                'added_count': 1,
                'removed_count': 0,
            },
        ],
    }
    result = build_changelog(changes)

    # Latest change is shown in full, with a formatted date.
    assert result['latest'] == {
        'date': '9 Jun 2026',
        'added': ['New Song - Artist A', 'Another One - Artist B'],
        'removed': ['Old Song - Artist C'],
    }

    # Earlier changes carry the same full shape (date + song lists) as the latest.
    assert result['earlier'] == [
        {
            'date': '2 Jun 2026',
            'added': ['Hey Jude - The Beatles'],
            'removed': [],
        },
    ]

    # No changes -> None
    assert build_changelog(None) is None
    assert build_changelog({'edition': 'current', 'entries': []}) is None
    # Entries with no additions or removals are ignored.
    assert build_changelog({'entries': [{'added': [], 'removed': []}]}) is None


def test_build_changelog_history_limit():
    """The earlier-changes list is capped at the history limit."""
    entries = [
        {
            'generated_at': f'2026-06-{day:02d}T00:00:00+00:00',
            'added': [f'Song {day}'],
            'removed': [],
            'added_count': 1,
            'removed_count': 0,
        }
        for day in range(20, 0, -1)  # 20 entries, newest-first
    ]
    result = build_changelog({'entries': entries}, history_limit=10)
    # 1 latest + 10 earlier shown out of 20 total.
    assert len(result['earlier']) == 10


def test_render_index_with_changelog(sample_supporter_stats):
    """Test that a songbook's changelog renders a 'What's new' panel."""
    files = [{
        'title': 'Current Songbook',
        'subject': 'Weekly',
        'url': 'https://example.com/current.pdf',
        'preview_image': 'previews/current.png',
        'filename': 'current.pdf',
        'changelog': {
            'latest': {
                'date': '9 Jun 2026',
                'added': ['Brand New Song - The Band'],
                'removed': ['Retired Song - Old Act'],
            },
            'earlier': [
                {
                    'date': '2 Jun 2026',
                    'added': ['An Older Addition - Some Artist'],
                    'removed': [],
                },
            ],
        },
    }]

    html = render_index(files, supporter_stats=sample_supporter_stats)

    assert "What's new" in html
    # The top summary no longer shows the (x added, x removed) counts.
    assert "What's new (" not in html
    assert 'Added' in html
    assert 'Removed' in html
    assert 'Brand New Song - The Band' in html
    assert 'Retired Song - Old Act' in html
    assert '9 Jun 2026' in html
    # Earlier changes are revealed via a button and list their songs in full.
    assert 'changelog-more' in html
    assert 'Earlier changes' in html
    assert '2 Jun 2026' in html
    assert 'An Older Addition - Some Artist' in html


def test_render_index_without_changelog(sample_files, sample_supporter_stats):
    """Test that songbooks without a changelog show no 'What's new' panel."""
    html = render_index(sample_files, supporter_stats=sample_supporter_stats)
    assert "What's new" not in html


def test_render_index_without_monthly_supporters(sample_files, sample_supporter_stats):
    """Test HTML template rendering without monthly supporters."""
    # Render template with empty list
    html = render_index(
        sample_files, 
        last_updated='2024-01-01T12:00:00Z',
        base_url='https://test.example.com',
        supporter_stats=sample_supporter_stats,
        monthly_supporters=[]
    )
    
    # Monthly supporters section should not be present
    assert 'Special thanks to our monthly supporters:' not in html


def test_verbose_output_get_latest_edition_info(capsys):
    """Test that get_latest_edition_info prints verbose output."""
    mock_bucket = MagicMock()
    mock_bucket.name = 'test-bucket'
    mock_blob = MagicMock()
    
    latest_json_content = json.dumps({
        "pdf_filename": "songbook-current.pdf",
        "manifest_filename": "songbook-current.manifest.json"
    })
    mock_blob.download_as_text.return_value = latest_json_content
    mock_bucket.blob.return_value = mock_blob
    
    get_latest_edition_info(mock_bucket, 'current')
    
    captured = capsys.readouterr()
    assert 'Fetching latest.json from:' in captured.out
    assert 'https://storage.googleapis.com/test-bucket/current/latest.json' in captured.out


def test_verbose_output_get_edition_manifest(capsys):
    """Test that get_edition_manifest prints verbose output."""
    mock_bucket = MagicMock()
    mock_bucket.name = 'test-bucket'
    mock_blob = MagicMock()

    manifest_content = json.dumps({
        "generated_at": "2024-01-01T12:00:00Z"
    })
    mock_blob.download_as_text.return_value = manifest_content
    mock_bucket.blob.return_value = mock_blob

    get_edition_manifest(mock_bucket, 'current', 'manifest.json')
    
    captured = capsys.readouterr()
    assert 'Fetching manifest from:' in captured.out
    assert 'https://storage.googleapis.com/test-bucket/current/manifest.json' in captured.out


def test_create_session_with_retry():
    """Test that create_session_with_retry creates a properly configured session."""
    session = create_session_with_retry(max_retries=3, backoff_factor=2)
    
    # Verify session has the right adapters
    assert "https://" in session.adapters
    assert "http://" in session.adapters
    
    # Verify the adapter is HTTPAdapter with retry config
    adapter = session.adapters["https://"]
    assert adapter.max_retries.total == 3
    assert adapter.max_retries.backoff_factor == 2
    assert 429 in adapter.max_retries.status_forcelist
    assert adapter.max_retries.respect_retry_after_header is True
    assert 'GET' in adapter.max_retries.allowed_methods
    assert adapter.max_retries.raise_on_status is False


def test_get_buymeacoffee_stats_success(requests_mock):
    """Test successful API call for stats."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    
    successful_data = {
        'data': [
            {'support_coffees': '5', 'support_coffee_price': '3'},
        ],
        'next_page_url': None
    }
    
    requests_mock.get(base_url, json=successful_data, status_code=200)
    
    try:
        result = get_buymeacoffee_stats()
        
        # Should succeed on first try
        assert result['total_amount'] == 15  # 5 * 3
        assert result['supporter_count'] == 1
        # Must request JSON so auth failures come back as a clean 401, not a login redirect
        assert requests_mock.last_request.headers.get('Accept') == 'application/json'
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_stats_fallback_on_error(requests_mock, capsys):
    """Test that get_buymeacoffee_stats returns fallback and logs the error body."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'

    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'

    # Mock: API returns a 502 with a diagnostic body (mirrors issue #32)
    requests_mock.get(base_url, status_code=502, text='Bad Gateway: upstream timed out')

    try:
        result = get_buymeacoffee_stats()

        # Should return fallback values
        assert result['total_amount'] == 912
        assert result['supporter_count'] == 61
        # The response body must be surfaced in logs for diagnosis
        captured = capsys.readouterr()
        assert 'status 502' in captured.out
        assert 'Bad Gateway: upstream timed out' in captured.out
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_stats_401_flags_token(requests_mock, capsys):
    """A 401 (expired/revoked token) should fall back and flag the token, not a phantom 502."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'

    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'

    # Mirrors the real failure: with Accept: application/json the API returns a clean 401
    requests_mock.get(base_url, status_code=401, json={'error': 'Unauthenticated.'})

    try:
        result = get_buymeacoffee_stats()

        # Falls back, and the log points at the token rather than a misleading gateway error
        assert result['total_amount'] == 912
        captured = capsys.readouterr()
        assert 'status 401' in captured.out
        assert 'Unauthenticated' in captured.out
        assert 'regenerate BUYMEACOFFEE_API_TOKEN' in captured.out
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_stats_timeout_logs_page(requests_mock, capsys):
    """A request timeout falls back and logs which page timed out."""
    import requests
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'

    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    requests_mock.get(base_url, exc=requests.exceptions.Timeout)

    try:
        result = get_buymeacoffee_stats()

        assert result['total_amount'] == 912  # fallback
        captured = capsys.readouterr()
        assert 'timed out after 10s on page 1' in captured.out
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_stats_logs_progress(requests_mock, capsys):
    """A successful fetch logs per-page progress (with running totals) and elapsed time."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'

    base_url = 'https://developers.buymeacoffee.com/api/v1/supporters'
    requests_mock.get(
        base_url,
        json={'data': [{'support_coffees': '3', 'support_coffee_price': '3'}], 'next_page_url': None},
        status_code=200,
    )

    try:
        get_buymeacoffee_stats()

        out = capsys.readouterr().out
        assert 'Requesting supporters page 1' in out   # progress, printed before the request
        assert 'running total 1' in out                # per-page running total
        assert 'page(s) in' in out                     # elapsed-time summary
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_subscriptions_success(requests_mock):
    """Test successful API call for subscriptions."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'
    
    base_url = 'https://developers.buymeacoffee.com/api/v1/subscriptions'
    
    successful_data = {
        'data': [
            {'payer_name': 'John Doe', 'subscription_is_cancelled': None},
        ],
        'next_page_url': None
    }
    
    requests_mock.get(base_url, json=successful_data, status_code=200)
    
    try:
        result = get_buymeacoffee_subscriptions()
        
        # Should succeed
        assert len(result) == 1
        assert 'John Doe' in result
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


def test_get_buymeacoffee_subscriptions_empty_on_error(requests_mock, capsys):
    """Test that get_buymeacoffee_subscriptions returns empty and logs the error body."""
    os.environ['BUYMEACOFFEE_API_TOKEN'] = 'test-token'

    base_url = 'https://developers.buymeacoffee.com/api/v1/subscriptions'

    # Mock: API returns a 502 with a diagnostic body (mirrors issue #32)
    requests_mock.get(base_url, status_code=502, text='Bad Gateway: upstream timed out')

    try:
        result = get_buymeacoffee_subscriptions()

        # Should return empty list
        assert result == []
        # The response body must be surfaced in logs for diagnosis
        captured = capsys.readouterr()
        assert 'status 502' in captured.out
        assert 'Bad Gateway: upstream timed out' in captured.out
    finally:
        if 'BUYMEACOFFEE_API_TOKEN' in os.environ:
            del os.environ['BUYMEACOFFEE_API_TOKEN']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
