from .models import RecipeVersion


def recipe_gaps(item, at=None):
    """Những phần còn thiếu định mức của món (BRU-20). Rỗng nghĩa là đủ để mở bán."""
    if item.no_ingredients:
        return []
    version = RecipeVersion.objects.current_for(item, at)
    if version is None:
        return ["định mức đã áp dụng (món chưa có phiên bản định mức nào)"]
    covered_sizes = set(version.lines.filter(size__isnull=False).values_list("size_id", flat=True))
    covered_options = set(version.lines.filter(option__isnull=False).values_list("option_id", flat=True))
    gaps = [f"định mức kích cỡ {size.name}" for size in item.active_sizes() if size.pk not in covered_sizes]
    gaps += [
        f"định mức tùy chọn {option.name} (hoặc đánh dấu Không dùng nguyên liệu)"
        for option in item.active_options().filter(no_ingredients=False)
        if option.pk not in covered_options
    ]
    return gaps


def ingredient_usage(version, size, options=()):
    """Lượng nguyên liệu cho một ly theo phiên bản đã lưu: {ingredient_id: lượng}.

    Dòng món ở phần tạo đơn sẽ lưu kết quả này cùng phiên bản (BRU-39).
    """
    size_id = getattr(size, "pk", size)
    option_ids = {getattr(o, "pk", o) for o in options}
    usage = {}
    for line in version.lines.all():
        if (line.size_id is not None and line.size_id == size_id) or (line.option_id is not None and line.option_id in option_ids):
            usage[line.ingredient_id] = usage.get(line.ingredient_id, 0) + line.quantity
    return usage
