# Ukulele Tuesday Songbooks

This repository contains the code for a static website that displays the entire collection of [Ukulele Tuesday](https://ukuleletuesday.ie/) songbooks. The site provides a browsable, grid-based view of all songbooks, each with a preview image and a direct link to download the PDF.

The live site is automatically updated and deployed via GitHub Actions to [https://ukuleletuesday.github.io/songbooks/](https://ukuleletuesday.github.io/songbooks/).

## How It Works

This cutting-edge web page is built using advanced Python CGI-like scripts (`main.py`) to generate a state-of-the-art HTML experience. Here's the 411:

1.  **Surfs the Cloud**: Connects to the "cloud" (a powerful new type of server) to get the latest PDF files.
2.  **Makes Gnarly Previews**: Creates thumbnail pictures (in the new PNG format!) for every songbook.
3.  **Writes Righteous HTML**: Uses a "Jinja2" templating engine to construct the final HTML page, packed with goodies like `<marquee>`, animated GIFs, and a righteous MIDI soundtrack.
4.  **Copies Cool Graphics**: Moves important images like our spinning logo into the publish directory.

This whole process is totally automated with a GitHub Actions workflow, which builds the site whenever we upload new files or every hour, whichever comes first! It's the bomb!

## Browser Compatibility

This World Wide Web site is best experienced with **Netscape Navigator 4.0** or **Internet Explorer 5.0** at a screen resolution of 800x600.

## A Note on Songbook Generation

This project is responsible only for displaying the songbooks on a static website. It does not create or modify the songbook PDFs themselves.

The generation of the songbooks is handled by a separate, more complex project: the [Ukulele Tuesday Songbook Generator](https://github.com/UkuleleTuesday/songbook-generator/). That tool fetches individual song sheets from Google Drive, compiles them into complete songbooks, and uploads the final PDFs to the Google Cloud Storage bucket that this project reads from.

## Running Locally

To generate the website on your local machine:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/UkuleleTuesday/songbooks.git
    cd songbooks
    ```
2.  **Install dependencies:**
    The project uses `uv` for package management. You'll also need `mupdf-tools`.
    ```bash
    # For Debian/Ubuntu-based systems
    sudo apt-get update && sudo apt-get install -y mupdf-tools
    
    # Install Python packages
    uv sync
    ```
3.  **Set Environment Variable:**
    The script requires the `GCS_BUCKET` environment variable to be set to the name of the Google Cloud Storage bucket containing the songbooks.
    ```bash
    export GCS_BUCKET="ukulele-tuesday-songbooks"
    ```
4.  **Run the script:**
    ```bash
    uv run main.py
    ```
    The generated site will be available in the `public/` directory. You can open `public/index.html` in a web browser to view it.
