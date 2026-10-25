export function marketLayout(items, width, height) {
  const positive = items.filter((item) => item.size_metric > 0);
  const values = (positive.length ? positive : items).map((item) => ({
    item,
    weight: positive.length ? item.size_metric : 1,
  }));
  const rectangles = [];
  function split(group, x, y, w, h) {
    if (!group.length) return;
    if (group.length === 1) {
      rectangles.push({ ...group[0].item, x, y, width: w, height: h });
      return;
    }
    const total = group.reduce((sum, entry) => sum + entry.weight, 0);
    let cut = 1,
      sum = group[0].weight;
    while (
      cut < group.length - 1 &&
      Math.abs(sum + group[cut].weight - total / 2) < Math.abs(sum - total / 2)
    ) {
      sum += group[cut++].weight;
    }
    const ratio = sum / total;
    if (w >= h) {
      split(group.slice(0, cut), x, y, w * ratio, h);
      split(group.slice(cut), x + w * ratio, y, w * (1 - ratio), h);
    } else {
      split(group.slice(0, cut), x, y, w, h * ratio);
      split(group.slice(cut), x, y + h * ratio, w, h * (1 - ratio));
    }
  }
  split(values, 0, 0, width, height);
  return rectangles;
}
