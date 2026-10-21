"""Parse keyed counters; absent data stays None. Retain original text separately."""
MM_STAT_FIELDS = ("orig_data_size", "compr_data_size", "mem_used_total", "mem_limit",
                  "mem_used_max", "same_pages", "pages_compacted", "huge_pages", "huge_pages_since")

def keyed(text):
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        name, value = fields[0].rstrip(":"), fields[1]
        scale = 1024 if len(fields) > 2 and fields[2] == "kB" else 1
        try:
            result[name] = int(value) * scale
        except ValueError:
            result[name] = value
    return result

def pressure(text):
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        values = {}
        for part in parts[1:]:
            name, value = part.split("=", 1)
            values[name] = int(value) if name == "total" else float(value)
        result[parts[0]] = values
    return result

def pressure_fraction(previous, current, elapsed):
    if previous is None or current is None or elapsed <= 0 or current < previous:
        return None
    return (current - previous) / (elapsed * 1_000_000)

def mm_stat(text):
    if text is None:
        return None
    values = [int(value) for value in text.split()]
    if len(values) < 7:
        raise ValueError("unsupported zram mm_stat layout: fewer than seven fields")
    result = {name: values[i] if i < len(values) else None for i, name in enumerate(MM_STAT_FIELDS)}
    result["extra_fields"] = values[len(MM_STAT_FIELDS):]
    return result

def swap_devices(text):
    if text is None:
        return None
    result = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) == 5:
            result.append({"path": fields[0], "type": fields[1], "size_bytes": int(fields[2])*1024,
                           "used_bytes": int(fields[3])*1024, "priority": int(fields[4])})
    return result
