#!/usr/bin/env python3
"""Test script for build functionality."""

import os
import json
import pytest
import requests_mock

# Import functions from build.py for testing
from build import get_buymeacoffee_stats, get_buymeacoffee_subscriptions, render_index, get_manifest


@pytest.fixture
def test_env():
    """Test environment variables fixture."""
    return {
        'GCS_BUCKET': 'test-bucket',
        'BUYMEACOFFEE_API_TOKEN': 'test-token'
    }


@pytest.fixture
def mock_gcs_manifest():
    """Mock GCS manifest data fixture."""
    return {
        'last_updated_utc': '2024-01-01T12:00:00Z',
        'editions': {
            'test-edition': {
                'url': 'https://example.com/test.pdf'
            }
        }
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

def test_get_manifest(monkeypatch, mock_gcs_manifest):
    """Test manifest fetching from GCS."""
    from unittest.mock import MagicMock
    
    # Mock GCS client and bucket
    mock_blob = MagicMock()
    mock_blob.download_as_text.return_value = json.dumps(mock_gcs_manifest)
    
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    
    mock_client_instance = MagicMock()
    mock_client_instance.bucket.return_value = mock_bucket
    
    mock_client_class = MagicMock()
    mock_client_class.create_anonymous_client.return_value = mock_client_instance
    
    # Use monkeypatch to replace the storage.Client
    monkeypatch.setattr('build.storage.Client', mock_client_class)
    
    # Test manifest loading
    manifest = get_manifest('test-bucket')
    
    # Verify
    assert manifest['last_updated_utc'] == '2024-01-01T12:00:00Z'
    assert 'test-edition' in manifest['editions']

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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
