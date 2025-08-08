import os
import io
import shutil
import fitz  # PyMuPDF
from google.cloud import storage
from jinja2 import Environment, FileSystemLoader

# Configuration
BUCKET_NAME = os.environ['GCS_BUCKET']
OUTPUT_DIR = 'public'
PREVIEW_DIR = os.path.join(OUTPUT_DIR, 'previews')
TEMPLATE_DIR = 'templates'
TEMPLATE_FILE = 'index.html.j2'

def list_pdf_blobs(bucket_name):
    """Lists all PDF blobs in the bucket."""
    client = storage.Client.create_anonymous_client()
    bucket = client.bucket(bucket_name)
    blobs = client.list_blobs(bucket)

    def sort_key(blob):
        # Sort regular.pdf first, then others alphabetically
        is_regular = blob.name.lower() == 'regular.pdf'
        return (not is_regular, blob.name.lower())

    pdf_blobs = [blob for blob in blobs if blob.name.lower().endswith('.pdf')]
    return sorted(pdf_blobs, key=sort_key)

def process_pdf_blob(blob, preview_path):
    """
    Downloads a PDF blob, saves the first page as a PNG image,
    and returns its metadata.
    """
    print(f"  Processing {blob.name}...")
    pdf_data = blob.download_as_bytes()
    pdf_document = fitz.open(stream=pdf_data, filetype="pdf")

    # Generate preview image
    if len(pdf_document) > 0:
        first_page = pdf_document.load_page(0)
        pix = first_page.get_pixmap(dpi=150, alpha=True)
        pix.save(preview_path)

    # Extract metadata, fallback to filename for title
    metadata = pdf_document.metadata
    title = metadata.get('title') or blob.name.replace('.pdf', '')
    subject = metadata.get('subject', '') # Default to empty string if no subject

    return {'title': title, 'subject': subject}

def render_index(file_list, last_updated=None):
    """Renders the HTML index page."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(files=file_list, last_updated=last_updated)

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
    print(f"Fetching songbooks from GCS bucket: {BUCKET_NAME}")
    blobs = list_pdf_blobs(BUCKET_NAME)
    songbooks = []
    
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    last_updated = None
    if blobs:
        latest_blob = max(blobs, key=lambda b: b.updated)
        last_updated = latest_blob.updated.strftime('%B %d, %Y')

    for blob in blobs:
        sanitized_name = blob.name.replace(".pdf", "")
        preview_filename = f"{sanitized_name}.png"
        preview_path_abs = os.path.join(PREVIEW_DIR, preview_filename)
        
        metadata = process_pdf_blob(blob, preview_path_abs)

        songbooks.append({
            'title': metadata['title'],
            'subject': metadata['subject'],
            'url': f'https://storage.googleapis.com/{BUCKET_NAME}/{blob.name}',
            'preview_image': f'previews/{preview_filename}'
        })

    html = render_index(songbooks, last_updated=last_updated)
    write_output(html)
    print(f"Generated {len(songbooks)} songbooks → {OUTPUT_DIR}/index.html")
