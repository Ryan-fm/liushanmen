"""Print synthetic sports evidence with fresh timestamps for import testing."""
import csv
from datetime import datetime, timedelta, timezone
import sys

writer = csv.writer(sys.stdout)
writer.writerow(["text", "published_at", "source", "kind", "entity", "reference"])
sample = [
    ("城南杯东门扫码卡住，闸机暂时停用。", "票务工单", "internal", "T-901"),
    ("东门验票队伍已积压到广场。", "值班记录", "internal", "OPS-21"),
    ("城南杯东门入场较慢，观众被引导至南门。", "观众访谈", "media", ""),
    ("城南杯东门扫码卡住，闸机暂时停用。", "转发", "public", ""),
]
for index, (text, source, kind, reference) in enumerate(sample, start=1):
    writer.writerow([text, (datetime.now(timezone.utc) - timedelta(minutes=index * 5)).isoformat(),
                     "样例·" + source, kind, "城南杯 / 东门", reference])
