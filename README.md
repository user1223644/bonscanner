# Receipt Scanner MVP

...

## Prerequisites

- **Python 3.8+**
- **Tesseract OCR** installed on your system

### Install Tesseract (macOS)

```bash
brew install tesseract
brew install tesseract-lang  # For German language support
```

## Setup

1. **Create a virtual environment** (recommended):

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Running the App

1. **Start the backend**:

   ```bash
   python app.py
   ```

   The API will run at `http://localhost:5000`

2. **Open the frontend**:
   ```bash
   open index.html
   ```
   Or simply double-click `index.html` to open it in your browser.
