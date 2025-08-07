import os
from google.cloud import storage
from jinja2 import Environment, FileSystemLoader

# Configuration
BUCKET_NAME = os.environ['GCS_BUCKET']        # e.g. "my-ukulele-tuesday"
OUTPUT_DIR = 'public'                         # where GitHub Pages will serve
TEMPLATE_DIR = 'templates'
TEMPLATE_FILE = 'index.html.j2'

def list_blobs(bucket_name):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    return sorted([blob.name for blob in client.list_blobs(bucket)], key=str.lower)

def render_index(file_list):
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    tmpl = env.get_template(TEMPLATE_FILE)
    return tmpl.render(files=[{'name': f, 'url': f'https://storage.googleapis.com/{BUCKET_NAME}/{f}'} for f in file_list])

def write_output(html):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

if __name__ == '__main__':
    blobs = list_blobs(BUCKET_NAME)
    html   = render_index(blobs)
    write_output(html)
    print(f"Generated {len(blobs)} links → {OUTPUT_DIR}/index.html")
