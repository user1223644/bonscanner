
def parse_labels_from_request(req):
    """Extract labels from form data (list or comma-separated)."""
    labels = req.form.getlist('labels')
    if not labels and req.form.get('labels'):
        labels = [l.strip() for l in req.form.get('labels').split(',') if l.strip()]
    return labels
