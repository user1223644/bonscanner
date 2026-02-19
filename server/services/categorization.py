import re

from database import get_category_rules


def apply_auto_categorization(store_name, existing_labels, raw_text=None, payment_method=None, items=None):
    """Apply auto-categorization rules based on configured rules."""
    labels = list(existing_labels) if existing_labels else []
    rules = get_category_rules()

    if not rules:
        return labels

    store_value = (store_name or "").lower()
    text_value = (raw_text or "").lower()
    payment_value = (payment_method or "").lower()
    item_names = [str(it.get("name", "")).lower() for it in (items or []) if it.get("name")]

    def match_value(value, pattern, match_type):
        if not value:
            return False
        if match_type == "equals":
            return value == pattern
        if match_type == "regex":
            try:
                return re.search(pattern, value, re.IGNORECASE) is not None
            except re.error:
                return False
        return pattern in value

    for rule in rules:
        if not rule.get("is_active"):
            continue
        category_name = rule.get("category_name")
        if not category_name or category_name in labels:
            continue

        rule_type = (rule.get("rule_type") or "").lower()
        pattern = str(rule.get("pattern") or "").lower()
        match_type = (rule.get("match_type") or "contains").lower()

        matched = False
        if rule_type == "store":
            matched = match_value(store_value, pattern, match_type)
        elif rule_type == "keyword":
            matched = match_value(text_value, pattern, match_type)
        elif rule_type == "payment":
            matched = match_value(payment_value, pattern, match_type)
        elif rule_type == "item":
            matched = any(match_value(name, pattern, match_type) for name in item_names)

        if matched:
            labels.append(category_name)

    return labels
