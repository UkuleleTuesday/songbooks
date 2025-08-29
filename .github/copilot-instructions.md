# Ukulele Tuesday Songbooks

Ukulele Tuesday Songbooks is a Python-based static website generator that creates a browsable gallery of songbook PDFs. The script fetches PDFs from Google Cloud Storage, generates preview images, and creates a responsive HTML site deployed to GitHub Pages at https://songbooks.ukuleletuesday.ie/.

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Working Effectively

### Bootstrap and Setup (Automated via GitHub Actions)
The development environment setup is automated through the Copilot Setup workflow located at `.github/workflows/copilot-setup.yml`. This workflow handles:
- Installing system dependencies (mupdf-tools)
- Setting up the uv package manager
- Installing Python dependencies via `uv sync`
- Configuring required environment variables

The workflow can be triggered manually or will be automatically executed when GitHub Copilot coding agents begin work on this repository.

### Environment Configuration
- Required environment variable `GCS_BUCKET` is automatically set by the Copilot Setup workflow to `"ukulele-tuesday-songbooks"`
- CRITICAL: The application requires network access to Google Cloud Storage. It will fail in sandboxed environments or networks that block GCS access with a `Forbidden: 403` error.

### Build and Run
- Generate the website:
  ```bash
  uv run main.py  # Takes 10-60 seconds depending on number of songbooks. NEVER CANCEL.
  ```
- The generated site will be available in the `public/` directory
- View locally by serving the `public/` directory:
  ```bash
  cd public && python -m http.server 8000
  # Then open http://localhost:8000
  ```

## Validation

### Manual Testing Requirements
- ALWAYS manually validate any changes by running the complete build process and visually inspecting the output
- Test the generated website by serving it locally and checking:
  - All songbook cards display correctly with titles and subjects
  - Preview images load (will show placeholder if no actual PDFs processed)
  - Download links are properly formatted
  - Last updated timestamp displays correctly
  - Support section and footer display properly
  - CSS styling applies correctly
- ALWAYS test both successful builds and error conditions (missing environment variables, network issues)

### Automated Testing
- Run the template rendering test:
  ```bash
  python -c "
  import sys, os
  sys.path.append('.')
  os.chdir('.')
  from jinja2 import Environment, FileSystemLoader
  env = Environment(loader=FileSystemLoader('templates'))
  html = env.get_template('index.html.j2').render(files=[], last_updated=None)
  print('✅ Template renders successfully')
  "
  ```

### Build Timing Expectations
- **Copilot Setup Workflow**: ~3 minutes (automated setup of dependencies and environment)
- `uv sync`: ~30 seconds (downloads Python + dependencies, automated via workflow)
- `uv run main.py`: 10-60 seconds (depends on number of songbooks to process)
- NEVER CANCEL builds or long-running commands. Network operations may take time.

## Troubleshooting

### Common Issues
- **`KeyError: 'GCS_BUCKET'`**: The environment variable should be automatically set by the Copilot setup workflow. If missing, set manually: `export GCS_BUCKET="ukulele-tuesday-songbooks"`
- **`Forbidden: 403` or `net::ERR_BLOCKED_BY_CLIENT`**: Network access to Google Cloud Storage is blocked. This is expected in sandboxed environments.
- **`bash: uv: command not found`**: The uv package manager should be installed by the Copilot setup workflow. If missing, install manually: `pip install uv`
- **`ImportError: No module named 'fitz'`**: System dependencies should be installed by the Copilot setup workflow. If missing, install manually: `sudo apt-get install -y mupdf-tools`
- **Template rendering errors**: Check that `templates/index.html.j2` exists and is valid Jinja2 syntax

### Network Limitations
- The application CANNOT run without internet access to `storage.googleapis.com`
- In restricted environments, you can test template rendering and output generation using mock data
- The GitHub Actions deployment works because it runs in an unrestricted environment

## Common Tasks

### Repository Structure
```
.
├── README.md              # Project documentation
├── main.py               # Main application script
├── pyproject.toml        # Python dependencies
├── uv.lock              # Dependency lock file
├── .python-version      # Python version (3.10)
├── templates/
│   └── index.html.j2    # Jinja2 HTML template
├── assets/              # Static assets (CSS, images, logos)
│   ├── style.css
│   ├── ut-logo.png
│   ├── uke-closeup.jpeg
│   └── favicon.png
├── .github/
│   ├── copilot-instructions.md  # GitHub Copilot instructions
│   └── workflows/
│       ├── deploy.yml           # GitHub Actions deployment
│       └── copilot-setup.yml    # GitHub Copilot setup automation
└── public/              # Generated output (created by main.py)
    ├── index.html
    ├── assets/          # Copied from source assets/
    └── previews/        # Generated PDF preview images
```

### Key Files to Modify
- `main.py`: Core application logic (PDF processing, template rendering)
- `templates/index.html.j2`: HTML template for the website
- `assets/style.css`: Website styling
- `.github/workflows/deploy.yml`: Deployment configuration

### Development Workflow
1. Make changes to Python code or templates
2. Run `uv run main.py` to test generation locally
3. Serve `public/` directory to test in browser
4. Validate changes work with both real and mock data
5. Test that the build process completes without errors

### CI/CD Process
- GitHub Actions runs every 10 minutes (schedule) and on push to main
- Checks for changes in GCS bucket before running build
- Uses `uv sync` and `uv run main.py` to generate site
- Deploys to GitHub Pages automatically
- Build artifacts are in the `public/` directory

## Dependencies

### System Dependencies
- `mupdf-tools`: Required for PDF processing and preview generation
- Python 3.10+ (managed by uv)

### Python Dependencies (in pyproject.toml)
- `google-cloud-storage>=3.2.0`: GCS bucket access
- `jinja2>=3.1.6`: Template rendering  
- `pymupdf>=1.26.3`: PDF processing and preview generation

### Network Dependencies
- Access to `storage.googleapis.com` (Google Cloud Storage)
- Access to external fonts and CDNs for full website rendering

## Testing Scenarios

### Complete Validation Checklist
When making changes, ALWAYS verify:
- [ ] `uv sync` completes successfully
- [ ] `export GCS_BUCKET="ukulele-tuesday-songbooks"` is set
- [ ] `uv run main.py` runs without Python errors (may fail on network)
- [ ] `public/` directory is created with correct structure
- [ ] `public/index.html` contains valid HTML
- [ ] `public/assets/` directory contains all static files
- [ ] Template renders with mock data (test with empty songbooks list)
- [ ] Website displays correctly when served locally
- [ ] All links and styling work properly

Use this validation checklist before committing any changes to ensure the build process remains functional.