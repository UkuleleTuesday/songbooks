import os
import io
import shutil
import json
import fitz  # PyMuPDF
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

def render_index(file_list, last_updated=None, base_url=None):
    """Renders the HTML index page."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(files=file_list, last_updated=last_updated, base_url=base_url)

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

    html = render_index(songbooks, last_updated=last_updated, base_url=BASE_URL)
    write_output(html)
    print(f"Generated {len(songbooks)} songbooks → {OUTPUT_DIR}/index.html")
