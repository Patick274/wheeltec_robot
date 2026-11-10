#!/usr/bin/env python3
"""**示例 5a：通用"无资料开发"方法论示例**（只依赖 roslibpy，可在无 ROS
环境的客户端运行）。

定位：拿到一个陌生 ROS 服务端、手里没有文档时，怎么用代码把话题/服务/
动作的结构查出来并对接。输入任意资源名，自动完成：
"在资源列表中定位 → 查询类型 → 递归解析类型定义中的字段结构 → 打印
字段树 →（可选）实际订阅/调用验证"。

**不写死**任何具体资源的类型字符串、自省服务名、返回字段名：
- 自省服务（rosbridge 暴露的 rosapi 族）的命名空间是**运行时从服务
  列表里发现**的（找覆盖能力词集合的那个命名空间），不是写死 /rosapi；
- 返回结果的取值键是**宽容提取**的（按返回值的形状认，不认键名）。

用法：
    python introspection_probe.py --host 192.168.1.100 --port 9090 \
        --topic /robot_description
    python introspection_probe.py --host … --service /lift/jog
    python introspection_probe.py --host … --action /some_action
    python introspection_probe.py --host … --scan        # 只列资源清单
"""

from __future__ import annotations

import argparse
import sys

# -- 基础类型词表（ROS 消息定义的固定词汇，不是"某资源的类型字符串"）---------
_PRIMITIVES = {"bool", "byte", "char", "int8", "uint8", "int16", "uint16",
               "int32", "uint32", "int64", "uint64", "float32", "float64",
               "string", "time", "duration", "builtin_interfaces/Time",
               "builtin_interfaces/Duration"}


class Introspection:
    """rosbridge 自省能力的运行时封装（命名空间与取值键都是发现的）。"""

    # 能力词集合：一个命名空间下的服务名后缀覆盖这些动词，即认定为自省
    # 命名空间。这是 rosbridge 协议词汇（client 依赖的固定契约），不是
    # 某个具体资源的名字。
    _CAP_VERBS = ("topics", "services", "topic_type", "service_type",
                  "message_details", "service_request_details",
                  "service_response_details", "action_servers")

    def __init__(self, ros) -> None:
        self._ros = ros
        self._services = sorted(ros.get_services())
        if not self._services:
            raise RuntimeError("服务列表为空——rosbridge 不可达或未暴露自省")
        self._ns = self._discover_namespace()
        self._ops = {verb: f"{self._ns}/{verb}" for verb in self._CAP_VERBS
                     if f"{self._ns}/{verb}" in self._services}

    def _discover_namespace(self) -> str:
        """从服务列表发现自省命名空间（命中能力词最多的第一段路径）。"""
        from collections import Counter
        score: Counter = Counter()
        for name in self._services:
            parts = name.strip("/").split("/")
            if len(parts) == 2 and parts[1] in self._CAP_VERBS:
                score[parts[0]] += 1
        if not score:
            raise RuntimeError(
                "未发现自省命名空间——该 rosbridge 可能未加载 rosapi"
                f"（服务列表: {self._services[:20]}…）")
        ns, hits = score.most_common(1)[0]
        print(f"[发现] 自省命名空间: /{ns}（命中 {hits}/"
              f"{len(self._CAP_VERBS)} 个能力词）")
        return f"/{ns}"

    # -- 宽容调用与取值 -----------------------------------------------------------

    def _call(self, op: str, args: dict, timeout: float = 10.0):
        import threading

        import roslibpy
        full = self._ops.get(op)
        if full is None:
            raise RuntimeError(f"自省能力 {op!r} 不存在（{self._ns} 下只有 "
                               f"{sorted(self._ops)}）")
        done = threading.Event()
        box: dict = {}
        svc = roslibpy.Service(self._ros, full, "")
        svc.call(roslibpy.ServiceRequest(args),
                 lambda r: (box.update(resp=dict(r or {})), done.set()),
                 lambda e: (box.update(err=str(e)), done.set()))
        if not done.wait(timeout):
            raise TimeoutError(f"自省服务 {full} 超时（{timeout}s）")
        if "err" in box:
            raise RuntimeError(f"自省服务 {full} 报错: {box['err']}")
        return box["resp"]

    @staticmethod
    def _pick(resp: dict, want: str):
        """宽容取值：优先按语义键名，找不到按值的形状认（list[str] / str /
        list[dict]）。返回 (值, 实际用的键名)。"""
        if want == "str_list":
            for k in ("topics", "services", "actions", "types", "names"):
                if isinstance(resp.get(k), list):
                    return resp[k], k
            for k, v in resp.items():
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    return v, k
        if want == "str":
            for k in ("type", "name"):
                if isinstance(resp.get(k), str):
                    return resp[k], k
            for k, v in resp.items():
                if isinstance(v, str) and v:
                    return v, k
        if want == "typedefs":
            for k, v in resp.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v, k
        raise KeyError(f"无法从返回中识别 {want} 形状；原始返回: {resp}")

    # -- 对外操作 ------------------------------------------------------------------

    def topics(self) -> list[str]:
        resp = self._call("topics", {})
        values, key = self._pick(resp, "str_list")
        print(f"[记录] 话题列表取自 {self._ops['topics']} 的键 {key!r}")
        return sorted(values)

    def services(self) -> list[str]:
        return list(self._services)

    def action_servers(self) -> list[str]:
        if "action_servers" not in self._ops:
            # 退路：从话题列表按 *_action 命名习惯推断（ROS2）或 */goal 形态
            # （ROS1 actionlib）——标注为推断而非自省直读
            print("[记录] 无 action_servers 自省服务，动作清单按话题形态推断")
            goals = [t[:-5] for t in self.topics() if t.endswith("/goal")]
            return sorted(set(goals))
        resp = self._call("action_servers", {})
        values, key = self._pick(resp, "str_list")
        print(f"[记录] 动作清单取自 {self._ops['action_servers']} 的键 {key!r}")
        return sorted(values)

    def topic_type(self, topic: str) -> str:
        resp = self._call("topic_type", {"topic": topic})
        value, key = self._pick(resp, "str")
        print(f"[记录] 话题类型取自 {self._ops['topic_type']} 的键 {key!r}")
        return value

    def service_type(self, service: str) -> str:
        resp = self._call("service_type", {"service": service})
        value, key = self._pick(resp, "str")
        print(f"[记录] 服务类型取自 {self._ops['service_type']} 的键 {key!r}")
        return value

    def message_typedefs(self, msg_type: str) -> list[dict]:
        """递归解析消息定义：返回 typedef 链（每个含字段名/类型/数组信息）。

        键名宽容提取：typedef 内的字段名/类型/数组长三个列表，按"等长的
        list"形状识别，不认死键名（不同 rosbridge 版本键名有 fieldnames/
        field_names 等差异）。
        """
        resp = self._call("message_details", {"type": msg_type})
        typedefs, key = self._pick(resp, "typedefs")
        print(f"[记录] 消息定义取自 {self._ops['message_details']} 的键 "
              f"{key!r}（{len(typedefs)} 个 typedef）")
        return typedefs

    def service_typedefs(self, srv_type: str) -> tuple[list[dict], list[dict]]:
        req = self._call("service_request_details", {"type": srv_type})
        res = self._call("service_response_details", {"type": srv_type})
        return self._pick(req, "typedefs")[0], self._pick(res, "typedefs")[0]


def _norm_type(t: str) -> str:
    """"pkg/msg/Type" ↔ "pkg/Type" 归一（ROS2/ROS1 rosbridge 差异吸收）。"""
    parts = t.split("/")
    return f"{parts[0]}/{parts[-1]}" if len(parts) == 3 else t


def _is_primitive(t: str) -> bool:
    return _norm_type(t) in {_norm_type(p) for p in _PRIMITIVES}


def print_field_tree(typedefs: list[dict], root_type: str) -> None:
    """把 typedef 链打印成字段树（typedef[0] 是根，其余按类型名索引）。"""
    by_type = {}
    for td in typedefs:
        for k in ("type",):
            if k in td:
                by_type[_norm_type(str(td[k]))] = td
    if not by_type:
        print(f"  （typedef 里找不到类型键，原始: {typedefs[:1]}）")
        return

    def _rows(td: dict):
        """从 typedef 提取 (字段名, 字段类型, 数组长度) 行——等长列表形状。"""
        lists = [v for v in td.values()
                 if isinstance(v, list) and v and
                 all(isinstance(x, (str, int)) for x in v)]
        names = next((v for v in lists
                      if all(isinstance(x, str) for x in v)), [])
        types = [v for v in lists if v is not names
                 and all(isinstance(x, str) for x in v)]
        types = types[0] if types else []
        return zip(names, types)

    def _walk(t: str, depth: int, seen: set) -> None:
        td = by_type.get(_norm_type(t))
        if td is None or t in seen:
            return
        seen = seen | {t}
        for name, ftype in _rows(td):
            is_array = isinstance(name, str) and name.endswith("[]")
            base = str(ftype).rstrip("[]")
            suffix = "[]" if (is_array or str(ftype).endswith("[]")) else ""
            print("  " * depth + f"- {name}: {base}{suffix}")
            if not _is_primitive(base):
                _walk(base, depth + 1, seen)

    print(f"字段树（根类型 {root_type}）:")
    _walk(root_type, 1, set())


def probe_topic(ros, intro: Introspection, name: str) -> None:
    topics = intro.topics()
    if name not in topics:
        print(f"话题 {name} 不在清单中（共 {len(topics)} 个；相近: "
              f"{[t for t in topics if name.strip('/') in t][:5]}）")
        return
    ttype = intro.topic_type(name)
    print(f"话题 {name} 类型: {ttype}")
    print_field_tree(intro.message_typedefs(ttype), ttype)


def probe_service(ros, intro: Introspection, name: str) -> None:
    if name not in intro.services():
        print(f"服务 {name} 不在清单中")
        return
    stype = intro.service_type(name)
    print(f"服务 {name} 类型: {stype}")
    req, res = intro.service_typedefs(stype)
    print("── 请求字段树:")
    print_field_tree(req, stype)
    print("── 响应字段树:")
    print_field_tree(res, stype)


def probe_action(ros, intro: Introspection, name: str) -> None:
    servers = intro.action_servers()
    print(f"动作服务端清单: {servers or '(空)'}")
    # 动作的三段（goal/feedback/result）是同名话题形态：经话题类型查询
    # 反推动作类型，再按 ActionGoal→Goal 后缀规则解析三段定义
    topics = intro.topics()
    for suffix in ("goal", "feedback", "result"):
        t = f"{name}/{suffix}"
        if t in topics:
            ttype = intro.topic_type(t)
            print(f"{t} 类型: {ttype}")
            # ActionGoal 包装 → 内层 goal 字段的类型随 typedef 链展开
            print_field_tree(intro.message_typedefs(ttype), ttype)
        else:
            print(f"{t} 不在话题清单中")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):      # Windows 控制台中文兜底
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--topic")
    ap.add_argument("--service")
    ap.add_argument("--action")
    ap.add_argument("--scan", action="store_true", help="只列资源清单")
    args = ap.parse_args(argv[1:])

    import roslibpy
    ros = roslibpy.Ros(host=args.host, port=args.port)
    ros.run()
    if not ros.is_connected:
        print(f"连不上 {args.host}:{args.port}", file=sys.stderr)
        return 2
    try:
        intro = Introspection(ros)
        if args.scan or not (args.topic or args.service or args.action):
            print(f"话题 ×{len(intro.topics())}:")
            for t in intro.topics():
                print(f"  {t}")
            print(f"服务 ×{len(intro.services())}:")
            for s in intro.services():
                print(f"  {s}")
            print(f"动作服务端: {intro.action_servers()}")
        if args.topic:
            probe_topic(ros, intro, args.topic)
        if args.service:
            probe_service(ros, intro, args.service)
        if args.action:
            probe_action(ros, intro, args.action)
    finally:
        ros.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
