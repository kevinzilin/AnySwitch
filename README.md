# AnySwitch Node for ComfyUI

[English Version](#english-version)

这是一个功能强大且极其灵活的 ComfyUI 自定义节点，名为 `AnySwitch` (万能判断切换)。它旨在简化和自动化您的工作流，能根据一个输入是否存在，来智能地在两个不同的输入源之间进行切换，并且支持**任何类型**的数据。

## 解决了什么痛点？

在构建复杂的工作流时，我们经常遇到需要“二选一”的情况。例如：

*   如果加载了图片，就执行“图生图”流程；如果没有，就执行“文生图”流程。
*   如果连接了主模型，就使用主模型；如果没有，就使用备用的默认模型。
*   需要一个开关来快速启用或禁用工作流的某个部分，但又不想每次都断开/重连节点。

在过去，您可能需要手动更改连线或复制多份工作流。现在，有了 `AnySwitch`，这一切都可以自动化。

## ✨ 核心功能

*   **智能切换**：自动检测“优先输入”是否连接并有数据 (`is not None`)。
*   **万能兼容**：支持 ComfyUI 中的**任何数据类型**，包括 `MODEL`, `CLIP`, `VAE`, `IMAGE`, `LATENT`, `INT`, `STRING` 等。
*   **流程控制**：输出一个布尔值 (`True`/`False`)，告知您当前哪个输入被激活，可用于驱动更复杂的逻辑。
*   **简化工作流**：让您的节点图更整洁、更直观、更易于管理。

## 📦 安装方法

1.  打开您的终端或命令行工具。
2.  进入 ComfyUI 的自定义节点目录：`cd ComfyUI/custom_nodes/`
3.  克隆本仓库：`git clone <你的仓库URL>` (请替换成你的GitHub仓库地址)
4.  重启 ComfyUI。

## 🚀 使用方法

`AnySwitch` 节点非常简单，它有2个输入和2个输出。

### 节点输入

*   `优先输入 (Primary Input)`: 您的首选数据源。只要这个输入端有数据，节点就会选择它。
*   `备用输入 (Fallback Input)`: 您的备用数据源。只有当“优先输入”为空时，节点才会选择它。

### 节点输出

*   `是否启用优先 (Is Primary Active)`: 一个布尔值。如果使用了“优先输入”，则为 `True`；如果使用了“备用输入”，则为 `False`。
*   `输出结果 (Output)`: 从被选中的输入端传出的数据。

### 示例：文生图 / 图生图 自动切换

这是一个经典的用法。

1.  将 `Load Image` 节点的 `IMAGE` 输出连接到 `AnySwitch` 的 `优先输入`。
2.  将 `Empty Latent Image` 节点的 `LATENT` 输出连接到 `AnySwitch` 的 `备用输入`。
3.  将 `AnySwitch` 的 `输出结果` 连接到下一个流程节点（例如 `VAE Encode` 或 `KSampler`）。

**效果**：
*   当你在 `Load Image` 节点中加载了一张图片时，`AnySwitch` 会将这张图片的数据传递下去（触发图生图流程）。
*   当你没有加载图片时，`AnySwitch` 会自动切换，将 `Empty Latent Image` 的数据传递下去（触发文生图流程）。

你再也无需手动更改连线了！

---
<br>

# <a name="english-version"></a>English Version

## AnySwitch Node for ComfyUI

This is a powerful and highly flexible custom node for ComfyUI called `AnySwitch`. It is designed to simplify and automate your workflows by intelligently switching between two different inputs based on whether a primary input is provided. Best of all, it works with **ANY data type**.

## What Problem Does It Solve?

When building complex workflows, we often face "either-or" scenarios. For example:

*   If an image is loaded, run an "Image-to-Image" process; otherwise, run a "Text-to-Image" process.
*   If a primary model is connected, use it; otherwise, use a default fallback model.
*   Needing a quick way to enable or disable a part of the workflow without constantly disconnecting and reconnecting nodes.

Previously, this required manual rewiring or duplicating workflows. With `AnySwitch`, this entire process can be automated.

## ✨ Core Features

*   **Intelligent Switching**: Automatically detects if the "Primary Input" is connected and has data (`is not None`).
*   **Universal Compatibility**: Works with **any data type** in ComfyUI, including `MODEL`, `CLIP`, `VAE`, `IMAGE`, `LATENT`, `INT`, `STRING`, and more.
*   **Flow Control**: Outputs a boolean flag (`True`/`False`) indicating which input is active, allowing for even more complex conditional logic.
*   **Cleaner Workflows**: Keep your node graphs tidy, intuitive, and easier to manage.

## 📦 Installation

1.  Open your terminal or command prompt.
2.  Navigate to your ComfyUI custom nodes directory: `cd ComfyUI/custom_nodes/`
3.  Clone this repository: `git clone <YOUR_REPOSITORY_URL>` (Replace with your GitHub repository URL)
4.  Restart ComfyUI.

## 🚀 How to Use

The `AnySwitch` node is straightforward, featuring 2 inputs and 2 outputs.

### Node Inputs

*   `优先输入 (Primary Input)`: Your preferred input source. As long as this input receives data, it will be selected.
*   `备用输入 (Fallback Input)`: Your alternative input source. This will only be used if the "Primary Input" is empty.

### Node Outputs

*   `是否启用优先 (Is Primary Active)`: A boolean value. It is `True` if the primary input was used, and `False` if the fallback input was used.
*   `输出结果 (Output)`: The data passed through from the selected input.

### Example: Auto-Switching between Txt2Img and Img2Img

This is a classic use case.

1.  Connect the `IMAGE` output of a `Load Image` node to the `Primary Input` of the `AnySwitch` node.
2.  Connect the `LATENT` output of an `Empty Latent Image` node to the `Fallback Input`.
3.  Connect the `Output` of the `AnySwitch` to the next node in your process (e.g., a `VAE Encode` or directly to a `KSampler`).

**Result**:
*   When you load an image in the `Load Image` node, `AnySwitch` passes its data down the chain (triggering your Img2Img workflow).
*   When you don't load an image, `AnySwitch` automatically switches and passes the data from the `Empty Latent Image` node instead (triggering your Txt2Img workflow).

No more manual rewiring is needed!
