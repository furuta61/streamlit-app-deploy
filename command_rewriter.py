# command_rewriter.py
import re

def rewrite_commands(commands_text, price_dict):
    output_lines = []

    for line in commands_text.splitlines():
        original_line = line.strip()
        if not original_line:
            continue

        # symbol
        m_symbol = re.search(r"--symbol\s+(\w+)", original_line)
        if not m_symbol:
            output_lines.append(original_line)
            continue
        symbol = m_symbol.group(1)

        # direction
        m_dir = re.search(r"--direction\s+(buy|sell)", original_line)
        if not m_dir:
            output_lines.append(original_line)
            continue
        direction = m_dir.group(1)

        # 価格辞書に symbol が無い → 置換せずそのまま出力
        if symbol not in price_dict:
            output_lines.append(original_line)
            continue

        # GPT Vision OCR → float 値（bid/ask を同値にする）
        extracted_price = price_dict[symbol]

        # 置換（--entry の後の数値）
        new_line = re.sub(
            r"--entry\s+[-+0-9.,]+",
            f"--entry {extracted_price}",
            original_line
        )

        output_lines.append(new_line)

    return "\n".join(output_lines)
