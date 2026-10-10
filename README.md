# 电化学 · Electrochemistry

用于电化学数据处理的可复用 Codex skills。每个 skill 独立存放在 `skills/<skill-name>/`，后续可以在同一个仓库中添加更多技能。

## 当前技能

| 技能 | 用途 | 运行条件 |
| --- | --- | --- |
| [origin-electrochemical-sensitivity](skills/origin-electrochemical-sensitivity/SKILL.md) | 从浓度系列伏安曲线提取峰/谷到基线的电流响应，用 Origin 原生 fitLR 计算灵敏度 K，输出可编辑 OPJU、原生图和审计表格 | Windows、64 位 Python 3.11、64 位 OriginPro 2021、Chrome 或 Edge |

完整科学处理规则、基线选择和多峰流程见该技能的 `SKILL.md` 与 `references/`。技能保留原来的筛选阈值和拟合定义，发布版本仅调整安装路径说明并补充依赖和软件测试示例。

## 下载

- [仓库首页](https://github.com/zhengtangbo/electrochemistry)
- [下载整个仓库 ZIP](https://github.com/zhengtangbo/electrochemistry/archive/refs/heads/main.zip)

也可以执行：

```powershell
git clone https://github.com/zhengtangbo/electrochemistry.git
```

下载 ZIP 后先解压。仓库包含说明、程序和参考资源；OriginPro、Python 和浏览器需要在使用者电脑上自行安装。Origin 的软件授权不随技能提供。

## 安装 Python 运行环境

在解压后的仓库根目录打开 PowerShell。先安装 64 位 Python 3.11 和 64 位 OriginPro 2021；Origin 应已激活并能够正常独立启动。程序会核验 Origin 版本，其他版本不属于本技能的已验证范围。

```powershell
py -3.11 -m venv .venv
$taskPython = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$taskSkill = (Resolve-Path '.\skills\origin-electrochemical-sensitivity').Path
& $taskPython -m pip install -r "$taskSkill\requirements.txt"
& $taskPython -c "import sys, struct; print(sys.version); print('bitness:', struct.calcsize('P') * 8)"
```

输出应为 Python 3.11 和 64 位。如果没有 `py` 命令，使用你安装的 Python 3.11 的绝对路径替代 `py -3.11`。不要用其他 Python 版本替换已验证的版本。

依赖版本记录在各技能自己的 `requirements.txt` 中。参考风格 PNG 的渲染还需要 Chrome 或 Edge；程序支持常见安装位置及 PATH 中的 `chrome` / `msedge`。

## 在 Codex 中安装和调用

在支持 Skill Installer 的 Codex 中，可以发送：

> 使用 $skill-installer 从 https://github.com/zhengtangbo/electrochemistry 安装 skills/origin-electrochemical-sensitivity 这个技能。保留完整的脚本、references、assets、requirements.txt 和 examples。

需要将实际文件存放在 D 盘时，可以追加：

> 实际文件放在 D:/skill/origin-electrochemical-sensitivity，并在当前 Codex 版本能够发现的个人技能目录中创建指向它的目录联接。验证 SKILL.md 和全部资源可读。

当前官方文档的用户级发现目录是 `~/.agents/skills`；部分现有安装使用 `~/.codex/skills`。以当前客户端实际发现的位置为准，避免在两个入口安装同名副本。仅解压到一个普通目录不会自动完成全局安装。安装后如未出现，重新打开 Codex。

调用时说明运行环境和数据：

> 使用 $origin-electrochemical-sensitivity 分析这些浓度系列伏安曲线。使用我指定的 Python 3.11 虚拟环境，先检查原始曲线和基线规则，再完成 Origin 原生拟合与工程核验。

即使没有 Codex，也可以按下面的命令直接运行脚本；基线、峰窗口和浓度设置仍需要有科学依据。

## 先验证软件安装

仓库提供 [明确标记的合成测试数据](skills/origin-electrochemical-sensitivity/examples/synthetic/README.md)。它由数学公式构造，仅用于检查程序，**不是实验观测或传感器性能证据**。

只检查数据读取、峰提取和 Python 交叉核验，不启动 Origin：

```powershell
& $taskPython "$taskSkill\scripts\sensitivity.py" `
  --manifest "$taskSkill\examples\synthetic\manifest.json" `
  --output-root '.\outputs\synthetic-prepare' `
  --prepare-only
```

准备阶段的 `analysis.json` 应标记 `status: prepared`，`python_crosscheck.slope` 约为 2.0、截距约为 0.4，`peak_quality.json` 应为 `pass`。`--prepare-only` 不提供已验证的 Origin 灵敏度结果。

验证完整的原生 Origin 流程：

```powershell
& $taskPython "$taskSkill\scripts\sensitivity.py" `
  --manifest "$taskSkill\examples\synthetic\manifest.json" `
  --output-root '.\outputs\synthetic-origin'
```

这会启动程序的 Origin 自动化会话。成功时 `analysis.json` 为 `status: success`，K 约为 `2.0 uA/mM`，并输出可重新打开的 OPJU、原生 PNG/PDF、单独渲染的参考风格 SVG/PNG 和 QA 日志。软件测试通过不代表某个真实实验的基线选择或化学峰归属已经验证。

## 分析自己的实验数据

1. 在技能目录之外新建分析文件夹，保留原始数据。
2. 按 [manifest 格式](skills/origin-electrochemical-sensitivity/references/manifest.md) 填写 `manifest.json`。数据文件路径可以相对于 manifest；明确列名、单位、浓度、扫描分支、共同峰窗口和基线锚区。
3. 按 [基线选择规则](skills/origin-electrochemical-sensitivity/references/baseline-selection.md) 查看原始曲线和空白，记录基线依据及锚区敏感性检查。
4. 用自己的 manifest 替换上述命令中的合成示例路径，把 `--output-root` 指向独立分析文件夹。先准备核验，再完成 Origin 原生流程。

拟合定义为每个浓度的平均峰到基线响应对浓度的无权重线性回归，截距自由，不自动删点、平滑或优化 R²。质控失败时保留候选测量和质控报告，停止拟合；Origin 失败时不得把 Python 交叉核验冒称原生结果。

## 复现范围

复现时固定仓库提交、输入文件、manifest 和软件版本。比较数值时使用合理容差；时间戳、运行文件夹、绝对路径和工程文件元数据可能不同，不能用整个 OPJU 的字节完全相同作为跨电脑复现标准。

不提供真实实验数据、私人账号或密钥。参考图片仅作排版样式示意，其示例数值不应复制到自己的结果中。公开仓库不包含第三方软件的安装包或许可。

## 发布核验记录

2026-10-10，在已有依赖的 Windows 电脑上，以 Python 3.11.9 和 64 位 OriginPro 2021 验证发布副本：

- 原有三个程序、基线参考、manifest 参考和样式图片与本地源文件的 SHA-256 一致。
- 官方技能格式检查通过；本机用户名和固定任务路径已从发布说明中移除。
- 合成示例准备阶段与完整原生 Origin 流程均通过；K = 2.0 uA/mM、截距 = 0.4 uA、R² = 1，与预先声明的公式一致。
- 已确认 OPJU 重开后数据、图形和 K/R² 注释存在，原生与参考风格 PNG 已人工查看，交付副本哈希与原生源文件一致。
- 移位的合成峰被质控拒绝，没有拟合灵敏度，也没有启动 Origin。
- 固定依赖经过公开 PyPI 的安装解析检查（dry-run）。没有声称已完成另一台电脑上的全新安装验证。

新增 skill 时，在 `skills/` 下建立独立文件夹，包含自己的 `SKILL.md`、程序、依赖、参考资源和使用示例，再更新上方列表即可。
