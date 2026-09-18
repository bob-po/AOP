# Billing Invoice（Phase 30）+ Stripe Checkout / Webhook（Phase 31–32）

从用量计量生成发票，创建 Checkout Session，并通过 **Stripe Webhook** 确认支付。

## 表

| 表 | 迁移 | 说明 |
|----|------|------|
| `billing_invoices` | `008` | 发票快照（含 `paid_at`） |
| `billing_checkout_sessions` | `009`/`010` | Checkout + `payment_status`/`paid_at` |
| `billing_webhook_events` | `010` | 事件幂等 |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/billing/invoice?days=30` | 预览 JSON |
| `GET` | `/v1/billing/invoice.md?days=30` | Markdown |
| `POST` | `/v1/billing/invoices` | 持久化 |
| `GET` | `/v1/billing/invoices` | 列表 |
| `POST` | `/v1/billing/invoices/{id}/checkout` | Checkout Session |
| `GET` | `/v1/billing/checkouts` | Session 列表 |
| `POST` | `/v1/billing/webhooks/stripe` | **公开** Webhook（验签） |
| `POST` | `/v1/billing/checkouts/simulate-paid` | 本地标记已支付 |

处理事件：`checkout.session.completed` · `async_payment_succeeded` · `expired`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `STRIPE_SECRET_KEY` | 创建真实 Checkout |
| `STRIPE_WEBHOOK_SECRET` | Webhook HMAC 验签（`whsec_…`） |
| `STRIPE_WEBHOOK_TOLERANCE` | 时间窗秒数（默认 300） |
| `STRIPE_WEBHOOK_ALLOW_UNSIGNED` | `1` 允许无签名（仅本地） |
| `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` | 回跳 |

Stripe CLI 示例：

```bash
stripe listen --forward-to localhost:8080/v1/billing/webhooks/stripe
```

## Console

Settings → **用量**：Checkout / Dry-run；对 Session 点 **Mark paid**（走 simulate，需允许 unsigned 或未设 webhook secret）。

## 冒烟

```bash
python apps/orchestrator/scripts/phase30_invoice.py
python apps/orchestrator/scripts/phase31_stripe_checkout.py
python apps/orchestrator/scripts/phase32_stripe_webhook.py
```
