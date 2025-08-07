import os
import io
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
    return sorted([blob for blob in blobs if blob.name.lower().endswith('.pdf')], key=lambda b: b.name.lower())

def generate_preview(blob, preview_path):
    """Downloads a PDF blob and saves the first page as a PNG image."""
    print(f"  Generating preview for {blob.name}...")
    pdf_data = blob.download_as_bytes()
    pdf_document = fitz.open(stream=pdf_data, filetype="pdf")
    if len(pdf_document) > 0:
        first_page = pdf_document.load_page(0)
        pix = first_page.get_pixmap(dpi=150)
        pix.save(preview_path)

def render_index(file_list):
    """Renders the HTML index page."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(files=file_list)

def write_output(html):
    """Writes the rendered HTML to the output directory."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

if __name__ == '__main__':
    print(f"Fetching songbooks from GCS bucket: {BUCKET_NAME}")
    blobs = list_pdf_blobs(BUCKET_NAME)
    songbooks = []
    
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    for blob in blobs:
        sanitized_name = blob.name.replace(".pdf", "")
        preview_filename = f"{sanitized_name}.png"
        preview_path_abs = os.path.join(PREVIEW_DIR, preview_filename)
        
        generate_preview(blob, preview_path_abs)

        songbooks.append({
            'name': sanitized_name,
            'url': f'https://storage.googleapis.com/{BUCKET_NAME}/{blob.name}',
            'preview_image': f'previews/{preview_filename}'
        })

    html = render_index(songbooks)
    write_output(html)
    print(f"Generated {len(songbooks)} songbooks → {OUTPUT_DIR}/index.html")
