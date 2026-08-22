# vulnhunt

自动化黑盒漏洞挖掘编排框架（v0.3.10）。**Claude 当大脑做规划，Codex 当手去执行**——Claude 把目标拆成 JSON 任务列表，分发给并行 Codex 实例，循环多轮直至 `max_rounds`，产出漏洞发现与报告。

```
目标/上轮结果 → Claude 大脑 → Plan subagent → JSON tasks → Codex x N（并行） → 结果 → 下轮
                          └──────── 循环（默认最多 50 轮）──────────────┘
```

- **目标**：`*.imou.com`（授权范围），关注"垃圾漏洞"清单——安全头缺失、CORS/Self-XSS、版本号/方法名/类名泄露、账号/验证码爆破（见 `CLAUDE.md`）。
- **架构**：纯 stdlib、零第三方依赖、Python ≥ 3.11；本地依赖 `claude` 与 `codex` 两个 CLI。
- **状态**：单元测试 20 个全过；⚠️ **从未实跑过**，全链路待端到端验证。

## 快速开始

```bash
pip install -e .
vulnhunt doctor                       # 检查 claude / codex 是否可用
vulnhunt start "审计 imou.com 首页安全头配置"   # 先小目标试跑一轮
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 深度架构设计：状态机、stream-json 规划捕获、codex 会话续跑、进程管理、落盘协议（源码级） |
| [docs/usage.md](docs/usage.md) | 安装与命令、TUI 交互、运行产物目录、安全注意事项 |
| [docs/configuration.md](docs/configuration.md) | 配置项对照表与 `VULNHUNT_*` 环境变量（含"声明但未使用"字段） |
| [docs/testing.md](docs/testing.md) | 测试跑法、真实 CLI 门控、各测试文件覆盖点 |
| [docs/known-gaps.md](docs/known-gaps.md) | 已知缺口 / 待办（findings 不落盘、报告简陋、死代码等） |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 故障排查指南：环境、运行失败、Windows、resume、日志定位 |
| [docs/development.md](docs/development.md) | 开发 / 维护指南：改哪里速查、常见任务、测试规范、发布 |

## ⚠️ 授权与安全

仅对授权范围 `*.imou.com` 使用；工具会向目标发主动请求，且顶层 Claude 以 `bypassPermissions`、codex 以 `danger-full-access` 沙箱运行——无授权使用可能违法，请勿在目标之外误触发。详见 [docs/usage.md](docs/usage.md) 安全章节。

## 上手建议

1. `pip install -e .` → `vulnhunt doctor`；
2. 小目标试跑一轮，用 `vulnhunt log <run_dir> [--round N]` 或 `vulnhunt tui` 观察规划与执行；
3. 链路确认后，再按 `CLAUDE.md` 的漏洞清单规划全量挖掘；
4. 投入使用前先补 [docs/known-gaps.md](docs/known-gaps.md) 中标 ⭐ 的缺口（findings 落盘、报告完善）。
