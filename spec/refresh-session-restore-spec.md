## 一句话目标
> 页面刷新后，自动恢复当前会话的问答记录，而不是显示初始欢迎页面。用户应看到刷新前正在查看的对话内容。

## 问题分析

### 当前行为（Bug）
```
页面加载 → getSessions() 返回列表 → setActiveSessionId(第一个会话)
→ messages 为空 [] → hasMessages=false → 显示 WelcomeScreen（初始页）
→ 用户无法看到之前的对话，必须手动切换会话才能恢复
```

### 根因
`App.tsx` 的挂载 `useEffect` 只做了两件事：
1. 调用 `getSessions()` 加载会话列表
2. 设置 `activeSessionId` 为列表第一个

**但没有加载该会话的消息记录**，导致 `messages` 始终为空数组。

### 期望行为
```
页面加载 → 恢复上次活跃的 sessionId → 加载该会话消息 → 显示 ChatArea（带历史对话）
```

## 数据模型

### sessionStorage 持久化键
| 字段 | 类型 | 说明 |
|---|---|---|
| active_session_id | string | 当前活跃的会话 ID |

- 存储位置：浏览器 `sessionStorage`（同标签页有效，关闭标签页清除）
- 写入时机：`activeSessionId` 变化时
- 读取时机：页面挂载时

## 接口变更

### App 组件 useEffect（挂载）
| 动作 | 输入 | 行为 |
|---|---|---|
| 页面挂载 | 无 | 1. 从 sessionStorage 读取 `active_session_id`<br>2. 调用 `getSessions()` 获取列表<br>3. 若有持久化的 sessionID 且在列表中存在 → 设为活跃并加载消息<br>4. 若无持久化 ID 或不存在于列表 → 取最近一个会话设为活跃并加载消息<br>5. 若会话列表为空 → 不设置活跃会话，显示欢迎页 |

### 新增：activeSessionId 变化时写入 sessionStorage
| 触发条件 | 行为 |
|---|---|
| activeSessionId 变为非 null | 将值写入 sessionStorage 的 `rag_active_session_id` |

## 行为规则

1. **刷新恢复**：刷新页面后，自动恢复到刷新前正在查看的会话，并显示其消息记录。
2. **sessionStorage 持久化**：当前活跃会话 ID 存储在 sessionStorage 中，同一标签页内刷新不丢失。
3. **会话不存在处理**：若持久化的 sessionID 在后端列表中不存在（如后端重启清空），回退到选择最近一个会话。
4. **无会话时**：会话列表为空时不设置活跃会话，正常显示欢迎页。
5. **新建对话兼容**：新建对话后刷新，能正确恢复到该新对话（因为新建时会立即写入 sessionStorage）。
6. **不影响现有功能**：点击侧边栏切换会话、删除/重命名会话等原有逻辑不受影响。

## 边界

- 刷新时后端已重启（会话列表为空）→ 显示欢迎页，不报错
- 刷新时持久化的 sessionID 已被删除 → 回退到最近一个会话
- 多个标签页同时打开 → 各自维护独立的 sessionStorage，互不干扰
- 首次访问（无 sessionStorage、无会话）→ 显示欢迎页
- 会话有大量消息 → 完整加载，不截断

## 明确不做

- 不使用 localStorage（跨标签页共享不需要，sessionStorage 更安全）
- 不做离线缓存 / PWA 支持
- 不修改后端 API 或 SessionManager
- 不修改侧边栏组件 Sidebar
- 不修改 handleSelectSession 的核心逻辑（仅复用其消息加载能力）
