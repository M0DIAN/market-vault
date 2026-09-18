"""In-memory fault model only. This is NOT native platform qualification."""

import os
from pathlib import Path
from types import SimpleNamespace

from market_vault.cross_day_dataset import materialization as m, reader as r, _artifact_io as io
from market_vault.cross_day_dataset.artifact_models import _require


class MemoryFS:
    def __init__(self, monkeypatch, root):
        self.root = Path(root)
        self.nodes = {self.root: (object(), True, b"")}
        self.events = []
        self.scope_hook = self.create_hook = self.write_hook = self.rename_hook = self.read_hook = None
        self.remove_hook = self.recheck_hook = None
        self.sequence = 0
        monkeypatch.setattr(m, "os", SimpleNamespace(name="nt", getpid=os.getpid, urandom=self.nonce))
        monkeypatch.setattr(m, "_NativeScope", self.scope)
        monkeypatch.setattr(r, "_NativeScope", self.scope)
        monkeypatch.setattr(m, "_require_qualified", lambda scope: self.events.append("SIMULATED_CAPABILITY"))
        monkeypatch.setattr(m, "_exists", lambda path: path in self.nodes)
        monkeypatch.setattr(io, "_inventory", self.inventory)
        monkeypatch.setattr(m, "_inventory", self.inventory)
        monkeypatch.setattr(m, "_new_directory", self.mkdir)
        monkeypatch.setattr(m, "_write_member", self.write)
        monkeypatch.setattr(m, "_rename_directory_no_replace_windows", self.rename)
        monkeypatch.setattr(m, "shutil", SimpleNamespace(rmtree=self.remove))

    def nonce(self, count):
        assert count == 16
        self.sequence += 1
        return self.sequence.to_bytes(count, "big")

    def scope(self, root, **kwargs):
        assert root == self.root
        self.events.append("READ_ROOT")
        model = self

        class Scope:
            current_sid = "SIMULATED"
            filesystem = ("SIMULATED",)

            def __init__(self):
                self.root = root
                self.root_object = self.member(root, directory=True)
                self.handles = [self.root_object]

            def member(self, path, *, directory):
                node = model.nodes.get(path)
                _require(node is not None and node[1] is directory, "UNSAFE_PATH", "simulated missing/wrong type")

                class Object:
                    filesystem = ("SIMULATED",)
                    security = ("SIMULATED_PRIVATE",)
                    fd = 37

                    def recheck(self):
                        if model.recheck_hook:
                            model.recheck_hook(path)
                        current = model.nodes.get(path)
                        _require(current is not None and current[0] is node[0] and current[1] is directory,
                                 "UNSAFE_PATH", "simulated object replacement")

                    def read_bytes(self):
                        self.recheck()
                        if model.read_hook:
                            model.read_hook(path)
                        return model.nodes[path][2]

                    def close(self):
                        pass

                held = Object()
                held.path, held.identity, held.directory = path, node[0], directory
                return held

            def recheck(self):
                if model.scope_hook:
                    model.scope_hook()
                for item in self.handles:
                    item.recheck()

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        return Scope()

    def inventory(self, directory, scope):
        return tuple(sorted((p.relative_to(directory).as_posix(), "DIRECTORY" if n[1] else "FILE")
                            for p, n in self.nodes.items() if directory in p.parents))

    def mkdir(self, path, *_):
        assert path not in self.nodes
        self.events.append("CREATE")
        if self.create_hook:
            self.create_hook(path)
        self.nodes[path] = (object(), True, b"")

    def write(self, owner, name, data):
        m._check_owner(owner)
        path = owner.path / name
        for parent in reversed(path.parents):
            if owner.path in parent.parents and parent not in self.nodes:
                self.mkdir(parent)
                owner.members[parent.relative_to(owner.path).as_posix()] = owner.scope.member(parent, directory=True)
        assert name in owner.expected and path not in self.nodes
        self.nodes[path] = (object(), False, data)
        owner.members[name] = owner.scope.member(path, directory=False)
        self.events.append("WRITE:" + name)
        if self.write_hook:
            self.write_hook(owner, name)

    def mutate(self, path, data=None, *, replace=False):
        identity, directory, old = self.nodes[path]
        self.nodes[path] = (object() if replace else identity, directory, old if data is None else data)

    def rename(self, staging, final):
        self.events.append("RENAME")
        if self.rename_hook:
            self.rename_hook(staging, final)
        if final in self.nodes:
            raise m._DestinationExists()
        for path in tuple(self.nodes):
            if path == staging or staging in path.parents:
                self.nodes[final / path.relative_to(staging)] = self.nodes.pop(path)

    def copy_winner(self, staging, final):
        for path, node in tuple(self.nodes.items()):
            if path == staging or staging in path.parents:
                self.nodes[final / path.relative_to(staging)] = (object(), node[1], node[2])

    def remove(self, directory):
        self.events.append("REMOVE")
        if self.remove_hook:
            self.remove_hook(directory)
        for path in tuple(self.nodes):
            if path == directory or directory in path.parents:
                del self.nodes[path]

    def artifact(self, dataset_id):
        final = self.root / ("dataset_id=" + dataset_id)
        return {p.relative_to(final).as_posix(): n for p, n in self.nodes.items() if p == final or final in p.parents}

    @property
    def mutations(self):
        return tuple(e for e in self.events if e != "READ_ROOT" and e != "SIMULATED_CAPABILITY")
