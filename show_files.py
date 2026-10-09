"""
show_files.py - show all folders, sub-folders and files of a directory as a tree.

Usage:
    python show_files.py                         (current folder)
    python show_files.py E:\FAKE_NEWS_DETECTION  (any folder)
    python show_files.py . --save tree.txt       (also save the result to a text file)
    python show_files.py . --all                 (include venv, __pycache__, .git etc.)
"""
import argparse
import os

SKIP_DIRS = {"venv", ".venv", "env", "__pycache__", ".git", ".idea", ".vscode", "node_modules"}


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def build_tree(root, show_all=False):
    lines = [os.path.abspath(root)]
    counts = {"folders": 0, "files": 0}

    def walk(folder, prefix=""):
        try:
            entries = sorted(os.listdir(folder), key=lambda x: (not os.path.isdir(os.path.join(folder, x)), x.lower()))
        except PermissionError:
            lines.append(prefix + "[permission denied]")
            return
        if not show_all:
            entries = [e for e in entries if e not in SKIP_DIRS]
        for i, name in enumerate(entries):
            path = os.path.join(folder, name)
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            if os.path.isdir(path):
                counts["folders"] += 1
                lines.append(f"{prefix}{branch}[{name}]")
                walk(path, prefix + ("    " if last else "│   "))
            else:
                counts["files"] += 1
                lines.append(f"{prefix}{branch}{name}  ({human_size(os.path.getsize(path))})")

    walk(root)
    lines.append(f"\n{counts['folders']} folders, {counts['files']} files")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="E:/FAKE_NEWS_DETECTION")
    ap.add_argument("--save", help="save the tree to this text file")
    ap.add_argument("--all", action="store_true", help="do not hide venv/__pycache__/.git")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        print("Folder not found:", args.folder)
        return
    tree = build_tree(args.folder, args.all)
    print(tree)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(tree)
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
