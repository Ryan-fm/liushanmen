"""Small, clearly marked sandbox datasets."""
from datetime import timedelta

from .rules import template, validate
from .sources import iso, normalize, now

DEMOS = [
    {
        "intent": "主场比赛期间监测「秋季杯」，重点盯入场、验票、交通与接驳。近 48 小时内至少 3 条相关反馈时调查。",
        "title": "秋季杯 · 赛事现场",
        "signals": [
            ("东门验票扫码后一直转圈，换了一条队才进去。", "票务工单", "internal", "秋季杯 / 东门", "TK-241", 2),
            ("东门第二条队的闸机报错，麻烦安排人员处理。", "现场值班", "internal", "秋季杯 / 东门", "OP-18", 3),
            ("秋季杯东门检票设备有两台暂停，工作人员正在引导到相邻入口。", "场馆公告（样例）", "public", "秋季杯 / 东门", "", 4),
            ("南门验票正常，东门排队比之前长。", "观众访谈（样例）", "media", "秋季杯 / 东门", "", 5),
            ("东门验票扫码后一直转圈，换了一条队才进去。", "转发（样例）", "public", "秋季杯 / 东门", "", 1),
            ("散场接驳车等了 20 分钟，站牌缺少方向说明。", "现场值班", "internal", "秋季杯 / 北广场", "OP-19", 7),
            ("停车区到场馆的交通指引贴在出口内侧。", "观众访谈（样例）", "media", "秋季杯 / 停车区", "", 9),
            ("比赛结束后南门很快清场。", "现场值班", "internal", "秋季杯 / 南门", "OP-20", 11),
        ],
    },
    {
        "intent": "盯住游戏「远星纪行」新版本的玩家反馈，重点核实闪退、登录失败和存档问题。近 72 小时至少 3 条才提报。",
        "title": "远星纪行 · 版本发布",
        "signals": [
            ("2.3.1 更新后传送到港口就崩溃，重启仍可复现。", "玩家评论（样例）", "public", "远星纪行 / 2.3.1", "", 3),
            ("2.3.1 登陆界面黑屏，显卡驱动已更新。", "客服工单", "internal", "远星纪行 / 2.3.1", "SUP-24", 5),
            ("新版本打开地图时偶发闪退，附有复现日志。", "客服工单", "internal", "远星纪行 / 2.3.1", "SUP-25", 6),
            ("切换设备后读档慢，进度没丢。", "玩家评论（样例）", "public", "远星纪行 / 2.3.1", "", 10),
        ],
    },
    {
        "intent": "跟踪新品「南岸随行杯」的用户投诉，关注商品质量和售后。近 48 小时至少 3 条独立反馈才发起调查。",
        "title": "南岸随行杯 · 新品口碑",
        "signals": [
            ("灰色 500ml 横放一会儿杯盖漏水。", "商品评价（样例）", "public", "南岸随行杯 / 灰色 500ml", "A-188", 4),
            ("收到杯子后盖紧还是漏水，申请补发杯盖。", "客服工单", "internal", "南岸随行杯 / 灰色 500ml", "A-244", 5),
            ("灰色杯子密封不好，漏水申请退款。", "售后记录", "internal", "南岸随行杯 / 灰色 500ml", "A-272", 7),
            ("外箱有擦碰，杯身完好。", "商品评价（样例）", "public", "南岸随行杯 / 蓝色 350ml", "A-273", 10),
        ],
    },
]


def seed(database, engine, feeds):
    keys = []
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM meta WHERE name='demo_seed'").fetchone():
            return
        stamp = now()
        for demo in DEMOS:
            plan = validate({**template(demo["intent"]), "title": demo["title"]}, feeds)
            key = database.create(plan, demo["intent"], True, connection=connection)
            keys.append(key)
            records = [normalize({
                "text": text, "entity": entity, "reference": reference,
                "published_at": iso(stamp - timedelta(hours=hours)),
            }, default_source=source, default_kind=kind, synthetic=True)
                for text, source, kind, entity, reference, hours in demo["signals"]]
            database.ingest(key, records, connection=connection)
        connection.execute("INSERT INTO meta VALUES('demo_seed','1')")
    for key in keys:
        database.set_active(key, True)
        engine.run(key, "live")
        database.set_active(key, False)
