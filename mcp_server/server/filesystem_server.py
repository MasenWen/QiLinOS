import json
import os
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server")
server_name = '文件管理系统'

from core import config, formatters, validations
from pydantic import AfterValidator, BaseModel
from typing import Annotated, List
from enum import Enum
from datetime import datetime
from mcp.types import TextContent
from fnmatch import fnmatch


class CreateDirectoryInput(BaseModel):
    path: Annotated[str, AfterValidator(lambda path: validations.validate_path(path=path, validate_parent=True))]


class DirectoryTreeInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]


class GetAllowedPathsInput(BaseModel):
    pass


class GetFileInfoInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]


class FileStats(BaseModel):
    size: float
    created: datetime
    modified: datetime
    accessed: datetime
    is_directory: bool
    is_file: bool
    permissions: str


class ListDirectoryInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]


class SortByEnum(str, Enum):
    file_name = "file_name"
    size = "size"


class ListDirectoryWithSizeInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]
    sort_by: SortByEnum = SortByEnum.file_name


class MoveFileInput(BaseModel):
    source: Annotated[str, AfterValidator(validations.validate_path)]
    destination: Annotated[str, AfterValidator(lambda path: validations.validate_path(path=path, validate_parent=True))]


class ReadFileInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]


class ReadMultipleFilesInput(BaseModel):
    paths: List[str]


class SearchFilesInput(BaseModel):
    path: Annotated[str, AfterValidator(validations.validate_path)]
    pattern: str
    exclude_patterns: List[str] = []


class WriteFileInput(BaseModel):
    path: Annotated[str, AfterValidator(lambda path: validations.validate_path(path=path, validate_parent=True))]
    content: str


@mcp.tool()
async def create_directory(input: CreateDirectoryInput) -> str:
    """
    创建一个新目录或确保目录存在。可以一次创建多个目录。
    如果目录已经存在，此操作将静默成功。非常适合为项目设置目录结构
    或确保在执行其他操作之前存在所需的目录。
    @Input:
        input: 包含要创建目录路径的输入对象。
    @Output:
        string: 成功或错误消息。
    """
    try:
        os.makedirs(input.path, exist_ok=True)
        return f"目录已成功创建或已存在于：{input.path}"
    except PermissionError as e:
        return f"权限错误：无法创建目录 '{input.path}' - {e}"
    except Exception as e:
        return f"创建目录 '{input.path}' 时发生未知错误：{e}"


@mcp.tool()
async def directory_tree(input: DirectoryTreeInput) -> str:
    """
    获取文件和目录的递归树形视图，以 JSON 结构表示。
    每个条目包括 'name'、'type'（文件/目录）以及目录的 'children'。
    文件没有 children 数组，而目录始终有 children 数组（可能为空）。
    输出以 2 个空格缩进格式化，以便于阅读。仅适用于允许的目录。
    @Input:
        input: 包含要获取目录树路径的输入对象。
    @Output:
        string: 目录树的 JSON 文本。
    """

    class TreeEntry(BaseModel):
        file_name: str
        type: str
        children: List["TreeEntry"] = []

    def _build_tree_recursive(current_path: str) -> List[TreeEntry]:
        result = []
        try:
            if not os.path.isdir(current_path):
                return []

            with os.scandir(current_path) as entries:
                for entry in entries:
                    full_entry_path = os.path.join(current_path, entry.name)
                    try:
                        validations.validate_path(full_entry_path)
                    except PermissionError:
                        continue

                    entry_data = TreeEntry(
                        file_name=entry.name,
                        type="directory" if entry.is_dir() else "file",
                    )

                    if entry.is_dir():
                        entry_data.children.extend(_build_tree_recursive(full_entry_path))
                    result.append(entry_data)
        except Exception as e:
            pass

        return result

    try:
        tree_data = _build_tree_recursive(input.path)
        return json.dumps(
            [entry.model_dump(exclude_defaults=True) for entry in tree_data],
            indent=2,
            ensure_ascii=False
        )
    except FileNotFoundError:
        return f"错误：路径 '{input.path}' 未找到。"
    except NotADirectoryError:
        return f"错误：'{input.path}' 不是一个目录。"
    except PermissionError as e:
        return f"权限错误：{e}"
    except Exception as e:
        return f"生成目录树时发生未知错误：{e}"


@mcp.tool()
async def get_allowed_paths(input: GetAllowedPathsInput) -> str:
    """
    获取文件系统工具允许访问的所有路径的详细列表。
    此工具对于了解哪些目录可供操作至关重要。
    @Input:
        input: 无特定输入参数。
    @Output:
        string: 允许访问的目录路径列表，每行一个。
    """
    try:
        allowed_paths = config.ServerConfig().get_allowed_paths()

        if not allowed_paths:
            return "当前没有配置任何允许的路径。"

        formatted = "\n".join(allowed_paths)
        return formatted
    except Exception as e:
        return f"获取允许路径时发生错误：{e}"


@mcp.tool()
async def get_file_info(input: GetFileInfoInput) -> str:
    """
    检索文件或目录的详细元数据。返回包括大小、创建时间、最后修改时间、权限和类型在内的综合信息。
    此工具非常适合在不读取实际内容的情况下了解文件特性。仅适用于允许的目录。
    @Input:
        input: 包含要获取统计信息的文件路径的输入对象。
    @Output:
        string: 文件的统计信息，包括权限，以 JSON 格式表示。
    """
    try:
        # input.path 已经通过 validate_path 验证过了，是绝对路径

        # 检查路径是否存在
        if not os.path.exists(input.path):
            raise FileNotFoundError(f"路径 '{input.path}' 未找到。")

        raw_stats = os.stat(input.path)
        file_stats = FileStats(
            size=raw_stats.st_size,
            created=datetime.fromtimestamp(raw_stats.st_ctime),
            modified=datetime.fromtimestamp(raw_stats.st_mtime),
            accessed=datetime.fromtimestamp(raw_stats.st_atime),
            is_directory=os.path.isdir(input.path),
            is_file=os.path.isfile(input.path),
            permissions=oct(raw_stats.st_mode)[-3:]  # 获取文件权限的八进制表示的最后三位
        )

        return file_stats.model_dump_json(indent=2)
    except FileNotFoundError:
        return f"错误：路径 '{input.path}' 未找到。"
    except PermissionError as e:
        return f"权限错误：无法获取文件信息 - {e}"
    except Exception as e:
        return f"获取文件 '{input.path}' 信息时发生未知错误：{e}"


@mcp.tool()
async def list_directory(input: ListDirectoryInput) -> str:
    """
    获取指定路径下所有文件和目录的详细列表。
    结果通过 [FILE] 和 [DIR] 前缀清晰区分文件和目录。
    此工具对于理解目录结构和查找目录中的特定文件至关重要。
    仅适用于允许的目录。
    @Input:
        input: 包含要列出目录路径的输入对象。
    @Output:
        string: 文件/目录名称列表。
    """
    try:
        entries = os.scandir(input.path)
        formatted_list = []
        for entry in entries:
            if entry.is_dir():
                formatted_list.append(f"[DIR] {entry.name}")
            else:
                formatted_list.append(f"[FILE] {entry.name}")

        return "\n".join(formatted_list)
    except FileNotFoundError:
        return f"错误：目录 '{input.path}' 未找到。"
    except NotADirectoryError:
        return f"错误：'{input.path}' 不是一个目录。"
    except Exception as e:
        return f"列出目录 '{input.path}' 时发生错误：{e}"


@mcp.tool()
async def list_directory_with_size(input: ListDirectoryWithSizeInput) -> str:
    """
    获取指定路径下所有文件和目录的详细列表，包括大小。
    结果通过 [FILE] 和 [DIR] 前缀清晰区分文件和目录。
    此工具对于理解目录结构和查找目录中的特定文件非常有用。仅适用于允许的目录。
    @Input:
        input: 包含要列出目录路径和排序选项的输入对象。
    @Output:
        string: 格式化后的文件/目录列表，包含大小和摘要。
    """

    # 辅助函数：格式化文件大小
    def _format_size(size_bytes: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    # 辅助函数：根据指定方式排序条目
    def _sort_entries(detailed_entries: List[dict], sort_by: SortByEnum) -> List[dict]:
        if sort_by == SortByEnum.size:
            # 按大小降序排序。目录（大小为0）通常排在文件之后。
            # 为了更全面的排序，可以考虑目录在前，再按文件大小排序
            return sorted(detailed_entries, key=lambda e: (
                e["isDirectory"], -e["size"] if not e["isDirectory"] else 0, e["name"].lower()))

        return sorted(detailed_entries, key=lambda e: e["name"].lower())

    def _format_entry(entry_path: str, entry: os.DirEntry[str]) -> dict:
        try:
            stats = os.stat(entry_path)
            return {
                "name": entry.name,
                "isDirectory": entry.is_dir(),
                "size": stats.st_size,
                "mtime": datetime.fromtimestamp(stats.st_mtime),
            }
        except Exception:
            # 捕获异常，例如权限问题或文件损坏
            return {
                "name": entry.name,
                "isDirectory": entry.is_dir(),
                "size": 0,
                "mtime": datetime.fromtimestamp(0),  # 默认时间戳
            }

    # 辅助函数：格式化最终输出列表
    def _format_output(sorted_entries: List[dict]) -> List[str]:
        formatted_list = []
        for entry in sorted_entries:
            kind = "[DIR]" if entry["isDirectory"] else "[FILE]"
            name_padded = entry["name"].ljust(30)
            size_str = ""
            if not entry["isDirectory"]:
                size_str = _format_size(entry["size"]).rjust(10)

            formatted_list.append(f"{kind} {name_padded}{size_str}")
        return formatted_list

    try:
        valid_path = input.path

        if not os.path.isdir(valid_path):
            if os.path.exists(valid_path):
                return f"错误：'{valid_path}' 是一个文件，不是目录。"
            else:
                raise FileNotFoundError(f"错误：路径 '{valid_path}' 未找到。")

        detailed_entries = []
        with os.scandir(valid_path) as entries:
            for entry in entries:
                full_entry_path = os.path.join(valid_path, entry.name)
                try:
                    validations.validate_path(full_entry_path)
                    detailed_entries.append(_format_entry(full_entry_path, entry))
                except PermissionError:
                    continue
                except FileNotFoundError:
                    continue

        sorted_entries = _sort_entries(
            detailed_entries=detailed_entries,
            sort_by=input.sort_by
        )
        formatted_list = _format_output(sorted_entries)

        total_files = sum(1 for e in detailed_entries if not e["isDirectory"])
        total_dirs = sum(1 for e in detailed_entries if e["isDirectory"])
        total_size = sum(e["size"] for e in detailed_entries if not e["isDirectory"])

        summary = [
            "",
            f"总计: {total_files} 个文件, {total_dirs} 个目录",
            f"总大小: {_format_size(total_size)}",
        ]

        return "\n".join(formatted_list + summary)

    except FileNotFoundError:
        return f"错误：路径 '{input.path}' 未找到。"
    except NotADirectoryError:
        return f"错误：'{input.path}' 不是一个目录。"
    except PermissionError as e:
        return f"权限错误：{e}"
    except Exception as e:
        return f"列出目录 '{input.path}' 并获取大小时发生未知错误：{e}"


@mcp.tool()
async def move_file(input: MoveFileInput) -> str:
    """
    移动或重命名文件和目录。可以在一次操作中移动文件到不同目录并重命名它们。
    如果目标路径已存在，操作将失败。可跨不同目录操作，也可用于同一目录内的简单重命名。
    源路径和目标路径都必须在允许的目录范围内。
    @Input:
        input: 包含源路径和目标路径的输入对象。
    @Output:
        string: 成功或错误消息。
    """
    try:
        if os.path.exists(input.destination):
            return f"错误：目标路径 '{input.destination}' 已存在。移动操作将失败。"

        os.rename(input.source, input.destination)
        return f"已成功将 '{input.source}' 移动到 '{input.destination}'"
    except FileNotFoundError:
        return f"错误：源路径 '{input.source}' 或目标父目录未找到。"
    except PermissionError as e:
        return f"权限错误：无法移动文件 - {e}"
    except OSError as e:
        return f"操作错误：移动文件时发生问题 - {e}"
    except Exception as e:
        return f"移动文件时发生未知错误：{e}"


@mcp.tool()
async def read_file(input: ReadFileInput) -> str:
    """
    从文件系统中读取文件并返回其内容。
    @Input:
        input: 包含要读取文件路径的输入对象。
    @Output:
        string: 文件的内容。
    """
    try:
        with open(input.path, encoding="utf-8") as file:
            content = file.read()
        return f"{input.path}:\n{content}"
    except FileNotFoundError:
        return f"错误：文件 '{input.path}' 未找到。"
    except Exception as e:
        return f"读取文件 '{input.path}' 时发生错误：{e}"


@mcp.tool()
async def read_multiple_files(input: ReadMultipleFilesInput) -> List[TextContent]:
    """
    从文件系统读取多个文件并返回其内容。
    @Input:
        input: 包含要读取的文件路径列表的输入对象。
    @Output:
        List[TextContent]: 一个 TextContent 对象的列表，每个对象包含一个文件的内容。
    """

    # 辅助函数：读取单个文件
    def _read_single_file(path: str) -> TextContent:
        try:
            valid_path = validations.validate_path(path)

            if not os.path.exists(valid_path):
                raise FileNotFoundError(f"文件 '{path}' 未找到。")
            if not os.path.isfile(valid_path):
                raise IsADirectoryError(f"路径 '{path}' 是一个目录，不是文件。")

            with open(valid_path, encoding="utf-8") as file:
                content = file.read()
            return TextContent(type="text", text=f"文件: {path}\n内容:\n{content}")
        except UnicodeDecodeError as e:
            return TextContent(
                type="text",
                text=f"错误：读取文件 '{path}' 时发生 Unicode 解码错误：{str(e)}。请确保它是有效的文本文件。"
            )
        except FileNotFoundError as e:
            return TextContent(
                type="text",
                text=f"错误：文件 '{path}' 未找到。"
            )
        except IsADirectoryError as e:
            return TextContent(
                type="text",
                text=f"错误：{str(e)}"
            )
        except PermissionError as e:
            return TextContent(
                type="text",
                text=f"错误：没有权限读取文件 '{path}' - {str(e)}"
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=f"错误：读取文件 '{path}' 时发生未知错误：{str(e)}"
            )

    results = []
    for path in input.paths:
        result = _read_single_file(path)  # 调用内联的辅助函数
        results.append(result)
    return results


@mcp.tool()
async def search_files(input: SearchFilesInput) -> TextContent:
    """
    递归搜索匹配指定模式的文件和目录。
    从起始路径开始搜索所有子目录。搜索不区分大小写，并匹配部分名称。
    返回所有匹配项的完整路径。非常适合在不确切知道文件位置时查找文件。
    仅在允许的目录中搜索。
    @Input:
        input: 包含根路径、搜索模式和排除模式的输入对象。
    @Output:
        TextContent: 包含成功消息或错误信息的文本内容。
    """

    # 辅助函数：递归搜索文件
    def _search_files_recursive(
            root_path: str,
            pattern: str,
            exclude_patterns: List[str],
    ) -> List[str]:
        results = []

        def _search(current_path: str):
            try:
                validations.validate_path(current_path)
                entries = os.scandir(current_path)
            except Exception:
                return

            with entries:
                for entry in entries:
                    full_path = os.path.join(current_path, entry.name)

                    try:
                        validations.validate_path(full_path)

                        # 相对路径用于匹配排除模式
                        relative_path = os.path.relpath(full_path, root_path)

                        # 处理排除模式（转换为 glob 风格）
                        should_exclude = any(
                            fnmatch(relative_path.lower(), p.lower()) or fnmatch(full_path.lower(), p.lower())
                            # 模式匹配也应不区分大小写
                            for p in exclude_patterns
                        )
                        if should_exclude:
                            continue

                        if pattern.lower() in entry.name.lower():
                            results.append(full_path)

                        if entry.is_dir():
                            _search(full_path)
                    except Exception:
                        continue

        _search(root_path)
        return results

    try:
        root_path = input.path

        if not os.path.exists(root_path):
            raise FileNotFoundError(f"搜索根路径 '{root_path}' 未找到。")
        if not os.path.isdir(root_path):
            raise NotADirectoryError(f"搜索根路径 '{root_path}' 不是一个目录。")

        results = _search_files_recursive(
            root_path=root_path,
            pattern=input.pattern,
            exclude_patterns=input.exclude_patterns,
        )

        if not results:
            return TextContent(type="text", text="未找到匹配项。")

        return TextContent(
            type="text",
            text="\n".join(results),
        )
    except FileNotFoundError as e:
        return TextContent(type="text", text=f"错误：{e}")
    except NotADirectoryError as e:
        return TextContent(type="text", text=f"错误：{e}")
    except PermissionError as e:
        return TextContent(type="text", text=f"权限错误：无法执行搜索 - {e}")
    except Exception as e:
        return TextContent(type="text", text=f"搜索文件时发生未知错误：{e}")


@mcp.tool()
async def write_file(input: WriteFileInput) -> TextContent:
    """
    将内容写入文件系统中的文件。
    @Input:
        input: 包含要写入的文件路径和内容的输入对象。
    @Output:
        TextContent: 指示操作成功的消息。
    """
    try:
        # input.path 已经通过 validate_path 验证过了
        # 并且 validate_parent=True 确保了父目录的权限

        # 确保文件可以被写入，处理可能的编码问题
        with open(input.path, "w", encoding="utf-8") as file:
            file.write(input.content)
        return TextContent(
            type="text", text=f"文件已成功写入至 '{input.path}'"
        )
    except PermissionError as e:
        return TextContent(
            type="text",
            text=f"权限错误：无法写入文件 '{input.path}' - {e}"
        )
    except FileNotFoundError:
        return TextContent(
            type="text",
            text=f"错误：无法写入文件 '{input.path}'，目标路径或其父目录不存在。"
        )
    except UnicodeEncodeError as e:
        return TextContent(
            type="text",
            text=f"编码错误：无法将内容写入文件 '{input.path}' - {e}。请检查内容是否包含无效字符。"
        )
    except Exception as e:
        return TextContent(
            type="text",
            text=f"写入文件 '{input.path}' 时发生未知错误：{e}"
        )


def config_server():
    path_args = sys.argv[1:]

    if not path_args:
        path_args.append(os.path.abspath(os.sep))

    server_config = config.ServerConfig()
    for path in path_args:
        expanded_path = formatters.expand_home(path)
        validations.path_exists(expanded_path)
        validations.is_valid_dir(expanded_path)
        norm_path = formatters.normalize_path(expanded_path)
        server_config.allow_path(norm_path)


if __name__ == "__main__":
    config_server()
    # register_tools()
    mcp.run(transport='stdio')
