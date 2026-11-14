from pathlib import Path
import json

from .domain import explore, validate
from .storage import Store, fingerprint
from .comparison import normalize_policy


class Workbench:
    def __init__(self, root, state):
        self.root = Path(root)
        self.product = json.loads((self.root / "product.json").read_text(encoding="utf-8"))
        self.store = Store(Path(state) / "research.sqlite3")
        initial = json.loads((self.root / "fixtures" / "data.json").read_text(encoding="utf-8"))
        validate(initial)
        self.default_revision = self.store.put_dataset("演示材料", initial)

    def context(self):
        return {"product": self.product, "default_revision": self.default_revision,
                "datasets": self.store.datasets(), "notebooks": self.store.notebooks()}

    def upload(self, body):
        data = body["data"]
        try:
            validate(data)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("字段结构不完整或类型不符") from error
        return {"revision": self.store.put_dataset(body.get("label", ""), data)}

    def inspect(self, body):
        revision = body.get("revision", self.default_revision)
        selection = body.get("selection", self.product["selection"])
        if not isinstance(selection, dict):
            raise ValueError("选择条件必须是对象")
        data = self.store.dataset(revision)
        # 页面提交的误差约定随本次计算生效；保存时进入 selection 一并冻结，
        # 重新打开旧记录不会被新数据自带的 limits 覆盖。
        policy = normalize_policy(body.get("tolerance"), data)
        frozen_selection = dict(selection)
        frozen_selection["tolerance"] = {"absolute": policy["absolute"], "relative": policy["relative"]}
        result = explore(data, selection, frozen_selection["tolerance"])
        return {"revision": revision, "selection": frozen_selection,
                "data_sha256": fingerprint(data), "view": result}

    def save(self, body):
        result = self.inspect(body)
        return self.store.save(body.get("title", ""), result["revision"], result["selection"], result)
