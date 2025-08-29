#!/usr/bin/env python3
"""Test script for build functionality."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import json

# Import functions from build.py for testing
from build import get_buymeacoffee_stats, render_index, get_manifest

class TestBuildFunctions(unittest.TestCase):
    """Test cases for build functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_env = {
            'GCS_BUCKET': 'test-bucket',
            'BUYMEACOFFEE_API_TOKEN': 'test-token'
        }

    @patch.dict(os.environ, {'BUYMEACOFFEE_API_TOKEN': 'test-token'})
    @patch('build.requests.get')
    def test_get_buymeacoffee_stats_pagination(self, mock_get):
        """Test Buy Me a Coffee API pagination."""
        # Mock API responses for multiple pages
        mock_responses = [
            # Page 1 - full page
            MagicMock(status_code=200, json=lambda: {
                'data': [
                    {'support_coffees': '5', 'support_coffee_price': '3'},
                    {'support_coffees': '2', 'support_coffee_price': '5'},
                ] * 25  # 50 supporters total (25 * 2)
            }),
            # Page 2 - partial page (indicates end)
            MagicMock(status_code=200, json=lambda: {
                'data': [
                    {'support_coffees': '10', 'support_coffee_price': '3'},
                    {'support_coffees': '1', 'support_coffee_price': '4'},
                ]
            }),
        ]
        mock_get.side_effect = mock_responses

        result = get_buymeacoffee_stats()
        
        # Verify pagination worked
        self.assertEqual(mock_get.call_count, 2)
        
        # Check first call parameters
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call[1]['params']['page'], 1)
        self.assertEqual(first_call[1]['params']['per_page'], 50)
        
        # Check second call parameters
        second_call = mock_get.call_args_list[1]
        self.assertEqual(second_call[1]['params']['page'], 2)
        self.assertEqual(second_call[1]['params']['per_page'], 50)
        
        # Verify calculations
        # Page 1: 25 * (5*3 + 2*5) = 25 * 25 = 625
        # Page 2: 10*3 + 1*4 = 34
        # Total: 625 + 34 = 659
        self.assertEqual(result['total_amount'], 659)
        self.assertEqual(result['supporter_count'], 52)
        self.assertEqual(result['currency'], '€')

    @patch.dict(os.environ, {'BUYMEACOFFEE_API_TOKEN': 'test-token'})
    @patch('build.requests.get')
    def test_get_buymeacoffee_stats_api_error(self, mock_get):
        """Test Buy Me a Coffee API error handling."""
        mock_get.side_effect = Exception("Network error")
        
        result = get_buymeacoffee_stats()
        
        # Should return fallback values
        self.assertEqual(result['total_amount'], 912)
        self.assertEqual(result['supporter_count'], 61)
        self.assertEqual(result['currency'], '€')

    @patch.dict(os.environ, {}, clear=True)
    def test_get_buymeacoffee_stats_no_token(self):
        """Test Buy Me a Coffee when no API token is provided."""
        result = get_buymeacoffee_stats()
        
        # Should return fallback values
        self.assertEqual(result['total_amount'], 912)
        self.assertEqual(result['supporter_count'], 61)
        self.assertEqual(result['currency'], '€')

    @patch.dict(os.environ, {'BUYMEACOFFEE_API_TOKEN': 'test-token'})
    @patch('build.requests.get')
    def test_get_buymeacoffee_stats_invalid_data(self, mock_get):
        """Test Buy Me a Coffee API with invalid data types."""
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            'data': [
                {'support_coffees': 'invalid', 'support_coffee_price': '3'},
                {'support_coffees': '2', 'support_coffee_price': 'also_invalid'},
                {'support_coffees': '5', 'support_coffee_price': '4'},  # Valid entry
            ]
        })
        
        result = get_buymeacoffee_stats()
        
        # Should only count the valid entry: 5 * 4 = 20
        self.assertEqual(result['total_amount'], 20)
        self.assertEqual(result['supporter_count'], 3)  # All entries counted for supporter count

    def test_render_index(self):
        """Test HTML template rendering."""
        # Test data
        files = [
            {
                'title': 'Test Songbook',
                'subject': 'Folk Songs',
                'url': 'https://example.com/test.pdf',
                'preview_image': 'previews/test.png'
            }
        ]
        
        supporter_stats = {
            'total_amount': 500,
            'supporter_count': 25,
            'currency': '€'
        }
        
        # Render template
        html = render_index(
            files, 
            last_updated='2024-01-01T12:00:00Z',
            base_url='https://test.example.com',
            supporter_stats=supporter_stats
        )
        
        # Basic checks
        self.assertIn('Test Songbook', html)
        self.assertIn('Folk Songs', html)
        self.assertIn('€500', html)
        self.assertIn('25 supporters', html)
        self.assertIn('<!DOCTYPE html', html)

    @patch('build.storage.Client.create_anonymous_client')
    def test_get_manifest(self, mock_client):
        """Test manifest fetching from GCS."""
        # Mock GCS client and bucket
        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = json.dumps({
            'last_updated_utc': '2024-01-01T12:00:00Z',
            'editions': {
                'test-edition': {
                    'url': 'https://example.com/test.pdf'
                }
            }
        })
        
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        
        mock_client_instance = MagicMock()
        mock_client_instance.bucket.return_value = mock_bucket
        mock_client.return_value = mock_client_instance
        
        # Test manifest loading
        manifest = get_manifest('test-bucket')
        
        # Verify
        self.assertEqual(manifest['last_updated_utc'], '2024-01-01T12:00:00Z')
        self.assertIn('test-edition', manifest['editions'])

def run_tests():
    """Run all tests."""
    unittest.main(verbosity=2)

if __name__ == '__main__':
    run_tests()