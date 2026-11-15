# LoRA adapter 与 Hugging Face 分发

> 2026-11-15。回答“adapter 是什么、为什么还要基座、怎么传到 HF / 怎么一键下载”。
>
> **已上传**：`Rise-again/campus-lora-p4-v1`（public，173MB），revision `73d6f6f5310fee0ccb4aec00d39a6a13884109a9`。服务器经 `hf-mirror.com` 下载 10 个文件，adapter 与本地 MD5 一致（`51a706e2175f24c8df0a08039f26d2a0`）。

## 1. LoRA adapter 是什么

QLoRA/LoRA 微调不复制整个 7B 模型，只训练少量低秩矩阵（本项目的 adapter）：

| 项 | 值 |
|---|---|
| 基座 | `Qwen2.5-7B-Instruct`（约 15GB） |
| adapter | `adapter_model.safetensors` 约 **155MB** + `adapter_config.json` |
| 结构 | r=16，alpha=32，target 7 个投影层（q/k/v/o/up/down/gate） |
| 位置 | `data/sft/output/`（服务器） / 本地完整包内同路径 |

推理时 vLLM 加载基座，再把 adapter 挂上去：

```bash
vllm serve .../qwen2.5-7b-instruct --enable-lora --max-lora-rank 16 \
  --lora-modules campus-lora=/hy-tmp/campus/data/sft/output
```

后端 `.env` 设 `LLM_MODEL=campus-lora`。**生产回答用的是“基座 + adapter”这个组合**，不是单独的 adapter 文件。

## 2. 为什么还有基座模型

- LoRA 只保存“增量”，没有基座权重就无法推理；
- 计划 D-10 明确 **不把 adapter 合并进量化基座**：会掉精度、破坏量化标度，且回退基座不方便；
- “微调后的模型”在系统里表现为 `campus-lora` 这个模型名：vLLM 内部 = 基座权重 + adapter。基座只下载一次（`fetch_models.sh`），adapter 可热挂/热换。
- 如果确实要一个“独立单文件模型”，可以 merge 成 15GB fp16，但项目不使用这种方式（显存/回退/精度都不划算）。

## 3. Hugging Face 允许上传吗

可以。Hugging Face 支持上传 PEFT/LoRA adapter 和完整微调模型，公共/私有仓库均可；单文件上限远大于 155MB。注意：

- Qwen2.5-7B-Instruct 是 **Apache 2.0**，微调产物可分发；仓库 README 写明基座与许可证即可；
- **不要上传原始 SFT 训练数据**（本项目数据来自学校公开制度文档，但没必要随 adapter 发布）；adapter 权重本身不含训练语料；
- 仓库可设为 public（免费、下载方便）或 private（需 `HF_TOKEN`）；
- 国内服务器访问 HF 可能慢/不通，可用镜像 `HF_ENDPOINT=https://hf-mirror.com`。

## 4. 上传步骤（你来做，一次即可）

> **网络实测（2026-11-15）**：云服务器访问 `huggingface.co` 超时（`curl` 000），只能访问 `hf-mirror.com`（200）；镜像站**只支持下载、不支持上传**。所以上传请在 **Windows 本机** 做（或用浏览器/代理），不要在云服务器上执行上传。

本地完整包已提供可直接上传的目录：

```
D:\Desktop\CamScanner\campus-final-2026-11-15\campus-lora-p4-v1-upload.tar.gz
```

解包后约 170MB，含 `adapter_config.json`、`adapter_model.safetensors`、tokenizer 文件、模型卡 `README.md`，不含 checkpoint。

1. 解包：

```powershell
cd D:\Desktop\CamScanner\campus-final-2026-11-15
tar -xzf campus-lora-p4-v1-upload.tar.gz
```

2. 安装 CLI 并登录（Windows，需要能访问 huggingface.co）：

```powershell
py -m pip install -U huggingface_hub
hf auth login          # 旧版：huggingface-cli login
```

> 如果 `hf` 不在 PATH（常见），别折腾 PATH，直接用 Python 脚本上传（推荐）：
>
> ```powershell
> cd D:\Desktop\CamScanner\campus-final-2026-11-15
> py -m pip install -U huggingface_hub
> $env:HF_TOKEN="hf_xxx"       # 或运行后按提示粘贴
> py upload_adapter.py         # 自动用你的 HF 账号名
> ```
>
> 脚本会创建仓库、上传文件夹并打印 `ADAPTER_REPO` / `ADAPTER_REVISION`。不要给仓库名加 `< >`，PowerShell 会当成重定向。

3. 创建仓库并上传：

```powershell
hf repo create Rise-again/campus-lora-p4-v1 --repo-type model
hf upload Rise-again/campus-lora-p4-v1 .\campus-lora-p4-v1 .
```

如果不方便装 Python，也可以直接在 HF 网页“New model”创建仓库，然后把 `campus-lora-p4-v1` 里的文件拖拽上传（模型卡 README 会显示 base_model/license）。

4. 上传后记下 commit（revision）或 tag，写进 `backend/.env` 的 `ADAPTER_REVISION`，避免以后仓库更新导致版本漂移。

> 如果 Windows 也无法访问 huggingface.co，则跳过 HF：本地完整包已有 adapter，恢复时直接解包 `data/sft/output` 即可，不影响项目重启。

## 5. 一键下载（以后重启项目）

云服务器可访问 `hf-mirror.com`，下载时加 `--endpoint https://hf-mirror.com` 即可。

```bash
/hy-tmp/campus/venvs/dl/bin/python scripts/fetch_adapter.py \
  --repo Rise-again/campus-lora-p4-v1 \
  --revision 73d6f6f5310fee0ccb4aec00d39a6a13884109a9 \
  --endpoint https://hf-mirror.com
```

或写进 `backend/.env`：

```
ADAPTER_REPO=Rise-again/campus-lora-p4-v1
ADAPTER_REVISION=73d6f6f5310fee0ccb4aec00d39a6a13884109a9
```

然后 `python scripts/fetch_adapter.py`。下载到 `/hy-tmp/campus/data/sft/output`，校验 `adapter_config.json` 与 `adapter_model.safetensors` 存在；确认 `.env` 里 `LLM_MODEL=campus-lora`，再 `bash scripts/start.sh`。私有仓库先设 `HF_TOKEN`。

## 6. 与本地完整包的关系

即使不传 HF，`campus-final-2026-11-15/final-appdata-*.tar.gz` 的 `data/sft/output/` 已有 adapter，可直接解包恢复。HF 只是多一个远程、可版本化的分发渠道。
