"""OCR Service — Extract products from invoice images using Tesseract."""

import re


def process_invoice_image(image_file) -> list:
    """Process an uploaded invoice image and extract product lines."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        import pytesseract

        image = Image.open(image_file)

        # Convert to grayscale
        if image.mode != 'L':
            image = image.convert('L')

        # Upscale small images (Tesseract works best at 300+ DPI)
        w, h = image.size
        if w < 1500:
            scale = 1500 / w
            image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # Increase contrast aggressively
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)

        # Increase sharpness
        enhancer2 = ImageEnhance.Sharpness(image)
        image = enhancer2.enhance(2.0)

        # Binarize (black/white) using threshold
        image = image.point(lambda x: 0 if x < 140 else 255, '1')
        image = image.convert('L')

        # Try multiple Tesseract configs for best results
        configs = [
            '--psm 6 --oem 3',   # Assume uniform block of text
            '--psm 4 --oem 3',   # Assume single column of text
            '--psm 3 --oem 3',   # Fully automatic
        ]

        best_text = ''
        best_items = []

        for config in configs:
            try:
                text = pytesseract.image_to_string(image, lang='spa', config=config)
                items = parse_invoice_text(text)
                if len(items) > len(best_items):
                    best_items = items
                    best_text = text
            except Exception:
                continue

        # Fallback: try without Spanish lang
        if len(best_items) < 2:
            try:
                text = pytesseract.image_to_string(image, config='--psm 6')
                items = parse_invoice_text(text)
                if len(items) > len(best_items):
                    best_items = items
                    best_text = text
            except Exception:
                pass

        text = best_text
        items = best_items

        items = parse_invoice_text(text)

        # If no items found, return the raw text so user can see what Tesseract read
        if not items:
            return [{
                "name": "(Sin productos detectados automáticamente)",
                "quantity": 0,
                "unit_cost": 0,
                "total": 0,
                "raw_text": text[:500] if text else "Imagen no legible",
            }]

        return items

    except ImportError:
        return [{"name": "OCR no disponible", "quantity": 0, "unit_cost": 0, "total": 0,
                 "raw_text": "Instale: sudo apt install tesseract-ocr tesseract-ocr-spa"}]
    except Exception as e:
        return [{"name": f"Error: {str(e)}", "quantity": 0, "unit_cost": 0, "total": 0}]


# Header/footer lines to skip (anchored patterns)
_SKIP_LINE = re.compile(
    r'^\s*(factura\s*$|invoice|nota\s+cr|recibo|'
    r'n\.?i\.?t|c[eé]dula|fecha\s*:|n[uú]mero\s|'
    r'direcci[oó]n|tel[eé]fono|celular|cliente\s*:|vendedor\s*:|'
    r'forma\s+de\s+pago|condici[oó]n|'
    r'sub\s*-?\s*total|total\s+a\s+pagar|^\s*total\s*$|'
    r'iva\s*[\(\d]|descuento|base\s+grav|'
    r'descripci[oó]n\s+cantidad|producto\s+cant|precio\s+unidad|importe|'
    r'observaci|firma|autoriza|imprim|gracias|www\.|@|'
    r'para\s*:|de\s*:|vencimiento|pedido|numero|'
    r'fecha|^\s*total\b)',
    re.IGNORECASE
)


def parse_invoice_text(text: str) -> list:
    """Parse OCR text to extract product lines. Flexible matching for Tesseract output."""
    items = []
    lines = text.strip().split('\n')

    # Currency symbols to strip
    _cur = r'[\$€£]?'

    # Pattern 1: name qty price total (most common)
    p1 = re.compile(
        r'^(.{3,80}?)\s+'                       # product name
        r'(\d+[.,]?\d*)\s+'                      # quantity
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s+'     # unit price
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s*$'    # total
    )
    # Pattern 2: name qty total (no unit price)
    p2 = re.compile(
        r'^(.{3,80}?)\s+'
        r'(\d+[.,]?\d*)\s+'
        rf'{_cur}\s*(\d[\d.,]{{3,}})\s*{_cur}\s*$'
    )
    # Pattern 3: qty first then name then prices
    p3 = re.compile(
        r'^(\d+[.,]?\d*)\s+'
        r'(.{3,80}?)\s+'
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s+'
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s*$'
    )
    # Pattern 4: name followed by a price (single item)
    p4 = re.compile(
        r'^(.{5,60}?)\s+'
        rf'{_cur}\s*(\d[\d.,]{{3,}})\s*{_cur}\s*$'
    )
    # Pattern 5: lines with | or tab separators (tables)
    p5 = re.compile(
        r'^(.{3,80}?)[|\t]\s*'
        r'(\d+[.,]?\d*)\s*[|\t]\s*'
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s*[|\t]?\s*'
        rf'{_cur}\s*(\d[\d.,]*)\s*{_cur}\s*$'
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue
        if _SKIP_LINE.search(line):
            continue
        # Skip lines that are only numbers/symbols (no letters)
        if re.match(r'^[\d\s.,$/€£\-=+%:]+$', line):
            continue

        # Try patterns in order of specificity
        for pattern, extractor in [
            (p5, lambda m: (m.group(1).strip(), _num(m.group(2)), _num(m.group(3)), _num(m.group(4)))),
            (p1, lambda m: (m.group(1).strip(), _num(m.group(2)), _num(m.group(3)), _num(m.group(4)))),
            (p3, lambda m: (m.group(2).strip(), _num(m.group(1)), _num(m.group(3)), _num(m.group(4)))),
        ]:
            m = pattern.match(line)
            if m:
                name, qty, cost, total = extractor(m)
                if _valid(name, qty, cost, total):
                    items.append(_item(name, qty, cost, total))
                    break
        else:
            # Try p2 (name + qty + total)
            m = p2.match(line)
            if m:
                name, qty, total = m.group(1).strip(), _num(m.group(2)), _num(m.group(3))
                cost = total / max(qty, 1)
                if name and total > 0:
                    items.append(_item(name, qty, cost, total))
                    continue

            # Try p4 (name + single price)
            m = p4.match(line)
            if m:
                name, total = m.group(1).strip(), _num(m.group(2))
                if name and total > 0 and not re.match(r'^\d', name):
                    items.append(_item(name, 1, total, total))
                    continue

    return items


def _valid(name, qty, cost, total):
    if not name or len(name) < 3 or (cost <= 0 and total <= 0):
        return False
    # Reject names that are mostly numbers (likely OCR noise from header/footer)
    letters = sum(1 for c in name if c.isalpha())
    if letters < 3:
        return False
    # Reject known aggregate lines
    low = name.lower().strip()
    if low in ('subtotal', 'total', 'descuento', 'iva'):
        return False
    return True


def _item(name, qty, cost, total):
    if qty <= 0: qty = 1
    if cost <= 0 and total > 0: cost = total / qty
    if total <= 0 and cost > 0: total = cost * qty
    # Clean up OCR noise from name
    name = re.sub(r'^[\d/\-]+\s+', '', name)  # Remove leading dates like "30/12/2014 "
    name = re.sub(r'^[=\-_\*#]+\s*', '', name)  # Remove leading symbols like "== "
    name = name.strip()
    return {
        "name": name[:100],
        "quantity": round(qty, 2),
        "unit_cost": round(cost, 2),
        "total": round(total, 2),
    }


def _num(s):
    """Parse number: handles Colombian (15.000 = 15000), European (28,45) and OCR errors."""
    s = s.strip().replace('$', '').replace('€', '').replace('£', '').replace(' ', '')
    if not s:
        return 0.0
    # OCR fixes (only apply to chars that are clearly not part of a word)
    s = s.replace('l', '1').replace('O', '0').replace('o', '0').replace('S', '5').replace('I', '1')
    # Colombian thousands: 15.000 → 15000
    if '.' in s and ',' in s:
        if s.index('.') < s.index(','):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        s = s.replace(',', '') if len(parts[-1]) == 3 else s.replace(',', '.')
    elif '.' in s:
        parts = s.split('.')
        if len(parts) > 1 and len(parts[-1]) == 3:
            s = s.replace('.', '')  # 15.000 → 15000
    try:
        return float(s)
    except ValueError:
        return 0.0
