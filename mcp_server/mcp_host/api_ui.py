from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

_HTML = """<!doctype html>
<html lang="zh-CN" data-bs-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>MCP 控制台</title>

  <link rel="stylesheet"
        href="https://fastly.jsdelivr.net/npm/bootswatch@5.3.8/dist/litera/bootstrap.min.css" />
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/bootstrap-icons.css" />

  <style>
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    .truncate { max-width: 520px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: inline-block; vertical-align: bottom; }
    .table td, .table th { vertical-align: middle; }
    .soft { opacity: .88; }
    .chip { border: 1px solid var(--bs-border-color); border-radius: 999px; padding: .2rem .55rem; font-size: .8rem; }
    .brand-dot { width: 10px; height: 10px; border-radius: 999px; background: var(--bs-primary); display:inline-block; margin-right:.5rem; }
    .modal-backdrop { opacity: .2 !important; }
  </style>
</head>

<body class="bg-body-tertiary">
  <nav class="navbar navbar-expand-lg bg-body shadow-sm">
    <div class="container-fluid">
      <a class="navbar-brand fw-semibold" href="/ui">
        <span class="brand-dot"></span>MCP 工具控制台
      </a>

      <div class="d-flex gap-2 align-items-center">
        <a class="btn btn-outline-secondary btn-sm" href="/docs" target="_blank">
          <i class="bi bi-journal-text me-1"></i>接口文档
        </a>
        <button class="btn btn-outline-secondary btn-sm" onclick="downloadConfig()">
          <i class="bi bi-download me-1"></i>导出配置
        </button>
        <button class="btn btn-primary btn-sm" onclick="refresh()">
          <i class="bi bi-arrow-clockwise me-1"></i>刷新
        </button>
      </div>
    </div>
  </nav>

  <main class="container py-4">
    <div class="row g-3 mb-3">
      <div class="col-12 col-lg-8">
        <div class="card shadow-sm">
          <div class="card-body d-flex justify-content-between align-items-center">
            <div>
              <div class="fw-semibold">服务器管理</div>
              <div class="text-secondary small">注册 / 启动 / 关闭 / 查看工具 / 导出 Cursor 可复用的 MCP 配置</div>
            </div>
            <div class="d-flex gap-2">
              <span class="chip"><i class="bi bi-hdd-stack me-1"></i><span id="serverCount">-</span> 个服务器</span>
              <span class="chip"><i class="bi bi-link-45deg me-1"></i><span id="connectedCount">-</span> 已连接</span>
            </div>
          </div>
        </div>
      </div>

      <div class="col-12 col-lg-4">
        <div class="card shadow-sm">
          <div class="card-body">
            <div class="fw-semibold mb-2">快速操作</div>
            <div class="d-grid gap-2">
              <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addModal">
                <i class="bi bi-plus-circle me-1"></i>新增服务器
              </button>
              <button class="btn btn-outline-secondary" onclick="openLogs()">
                <i class="bi bi-activity me-1"></i>查看日志
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-end mb-3">
          <div>
            <div class="fw-semibold">服务器列表</div>
            <div class="text-secondary small">状态：运行中 / 连接中 / 失败 / 已停止（失败原因可鼠标悬停查看）</div>
          </div>

          <div class="d-flex gap-2 align-items-center">
            <div class="input-group input-group-sm" style="width: 320px;">
              <span class="input-group-text"><i class="bi bi-search"></i></span>
              <input id="filter" class="form-control" placeholder="搜索（名称/描述）" oninput="render()" />
            </div>
          </div>
        </div>

        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead class="table-light">
              <tr>
                <th style="width: 170px;">名称</th>
                <th style="width: 420px;">描述</th>
                <th style="width: 420px;">脚本路径</th>
                <th style="width: 110px;">自启</th>
                <th style="width: 140px;">状态</th>
                <th class="text-end" style="width: 320px;">操作</th>
              </tr>
            </thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>

      </div>
    </div>

    <div class="position-fixed bottom-0 end-0 p-3" style="z-index: 1080;">
      <div id="toast" class="toast align-items-center border-0" role="alert" aria-live="assertive" aria-atomic="true">
        <div class="d-flex">
          <div id="toastBody" class="toast-body"></div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
      </div>
    </div>
  </main>

  <!-- 新增服务器 -->
  <div class="modal fade" id="addModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-lg modal-dialog-centered">
      <div class="modal-content shadow">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-plus-circle me-2"></i>新增服务器</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>

        <div class="modal-body">
          <div class="row g-3">
            <div class="col-12 col-md-4">
              <label class="form-label">名称（name）</label>
              <input id="new_name" class="form-control" placeholder="api_server" />
            </div>
            <div class="col-12 col-md-8">
              <label class="form-label">脚本路径（abs_path，可选）</label>
              <input id="new_path" class="form-control mono" placeholder="./mcp_server/server/api_server.py" />
              <div class="form-text">abs_path 或 filename 至少填写一个。</div>
            </div>

            <div class="col-12 col-md-6">
              <label class="form-label">文件名（filename，可选）</label>
              <input id="new_filename" class="form-control mono" placeholder="api_server.py" />
            </div>

            <div class="col-12 col-md-6">
              <label class="form-label">描述（可选）</label>
              <input id="new_desc" class="form-control" placeholder="一句话说明这个 server 的作用" />
            </div>

            <div class="col-12">
              <div class="d-flex gap-4 align-items-center">
                <div class="form-check form-switch">
                  <input class="form-check-input" type="checkbox" id="new_autostart">
                  <label class="form-check-label" for="new_autostart">注册后自动启动</label>
                </div>
                <div class="form-check form-switch">
                  <input class="form-check-input" type="checkbox" id="new_overwrite">
                  <label class="form-check-label" for="new_overwrite">覆盖同名</label>
                </div>
              </div>
            </div>

            <div class="col-12">
              <div class="alert alert-light border small mb-0">
                <div><b>校验规则</b>：name 只能包含字母/数字/_/-；脚本后缀仅支持 .py/.js/.mjs/.cjs；路径必须存在。</div>
              </div>
            </div>

          </div>
        </div>

        <div class="modal-footer">
          <button class="btn btn-outline-secondary" data-bs-dismiss="modal">取消</button>
          <button class="btn btn-primary" onclick="addServer()">
            <i class="bi bi-check2-circle me-1"></i>保存
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 工具列表 -->
  <div class="modal fade" id="toolsModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
      <div class="modal-content shadow">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-tools me-2"></i>工具列表</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>

        <div class="modal-body">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="text-secondary small" id="toolsHint"></div>
            <button class="btn btn-outline-secondary btn-sm" onclick="reloadTools()">
              <i class="bi bi-arrow-clockwise me-1"></i>刷新
            </button>
          </div>
          <div id="toolsBody"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- 日志 -->
  <div class="modal fade" id="logsModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
      <div class="modal-content shadow">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-activity me-2"></i>最近日志</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>

        <div class="modal-body">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="text-secondary small">用于展示与排障（读取 /logs）</div>
            <button class="btn btn-outline-secondary btn-sm" onclick="openLogs(true)">
              <i class="bi bi-arrow-clockwise me-1"></i>刷新
            </button>
          </div>
          <pre id="logsBody" class="bg-body-tertiary p-3 rounded small" style="white-space: pre-wrap;"></pre>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>

  <script>
    let ALL = [];
    let currentToolsServer = null;

    const toastEl = document.getElementById('toast');
    const toastBody = document.getElementById('toastBody');
    const toastObj = new bootstrap.Toast(toastEl, { delay: 2600 });

    function showToast(msg, type="success"){
      toastEl.className = "toast align-items-center text-bg-" + (type || "success") + " border-0";
      toastBody.textContent = msg;
      toastObj.show();
    }

    async function api(path, opts){
      const r = await fetch(path, Object.assign({ headers: { "Content-Type":"application/json" } }, opts||{}));
      const text = await r.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch(e) { data = { raw: text }; }
      if(!r.ok){
        const detail = (data && (data.detail || data.error)) ? (data.detail || data.error) : text;
        throw new Error(detail || ("HTTP " + r.status));
      }
      return data;
    }

    function esc(s){
      return String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
    }

    function badgeYesNo(v){
      if(v) return '<span class="badge text-bg-success"><i class="bi bi-check2 me-1"></i>是</span>';
      return '<span class="badge text-bg-secondary"><i class="bi bi-x me-1"></i>否</span>';
    }

    function badgeStatus(s, err){
      const st = (s || "stopped").toLowerCase();
      const title = err ? ` title="${esc(err)}"` : "";
      if(st === "ready") return `<span class="badge text-bg-success"${title}><i class="bi bi-play-fill me-1"></i>运行中</span>`;
      if(st === "connecting") return `<span class="badge text-bg-warning"${title}><i class="bi bi-hourglass-split me-1"></i>连接中</span>`;
      if(st === "failed") return `<span class="badge text-bg-danger"${title}><i class="bi bi-exclamation-triangle-fill me-1"></i>失败</span>`;
      return `<span class="badge text-bg-secondary"${title}><i class="bi bi-stop-fill me-1"></i>已停止</span>`;
    }

    function filtered(){
      const q = (document.getElementById("filter").value || "").trim().toLowerCase();
      if(!q) return ALL;
      return ALL.filter(s => (s.name||"").toLowerCase().includes(q) || (s.description||"").toLowerCase().includes(q));
    }

    function render(){
      const rows = filtered();
      const tbody = document.getElementById("tbody");
      tbody.innerHTML = "";

      let connectedCount = 0;
      for(const s of ALL){ if(s.connected) connectedCount++; }

      document.getElementById("serverCount").textContent = ALL.length;
      document.getElementById("connectedCount").textContent = connectedCount;

      for(const s of rows){
        const tr = document.createElement("tr");

        const pathHtml = s.abs_path
          ? `<span class="mono truncate" title="${esc(s.abs_path)}">${esc(s.abs_path)}</span>`
          : `<span class="text-secondary">-</span>`;

        const descHtml = s.description
          ? `<div class="soft">${esc(s.description)}</div>`
          : `<span class="text-secondary">-</span>`;

        const disableConnect = (s.status === "connecting" || s.connected);

        tr.innerHTML = `
          <td class="fw-semibold">${esc(s.name)}</td>
          <td>${descHtml}</td>
          <td>${pathHtml}</td>
          <td>${badgeYesNo(!!s.auto_start)}</td>
          <td>${badgeStatus(s.status, s.last_error)}</td>
          <td class="text-end">
            <div class="btn-group btn-group-sm" role="group">
              <button class="btn btn-outline-primary" ${disableConnect ? "disabled": ""} onclick="connectSrv('${esc(s.name)}')">
                <i class="bi bi-play-fill me-1"></i>启动
              </button>
              <button class="btn btn-outline-secondary" ${(!s.connected && s.status!=="connecting") ? "disabled": ""} onclick="disconnectSrv('${esc(s.name)}')">
                <i class="bi bi-stop-fill me-1"></i>关闭
              </button>
              <button class="btn btn-outline-secondary" onclick="openTools('${esc(s.name)}')" ${s.connected ? "" : "disabled"}>
                <i class="bi bi-tools me-1"></i>工具
              </button>
              <button class="btn btn-outline-danger" onclick="delSrv('${esc(s.name)}')">
                <i class="bi bi-trash3 me-1"></i>删除
              </button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function refresh(){
      try{
        const data = await api("/servers");
        ALL = data.servers || [];
        render();
      }catch(e){
        showToast("刷新失败：" + e.message, "danger");
      }
    }

    async function connectSrv(name){
      try{
        await api(`/servers/${name}/connect`, { method:"POST", body: JSON.stringify({}) });
        showToast("已启动并连接：" + name, "success");
        await refresh();
      }catch(e){
        showToast("启动失败：" + name + " - " + e.message, "danger");
        await refresh();
      }
    }

    async function disconnectSrv(name){
      try{
        await api(`/servers/${name}/disconnect`, { method:"POST", body: JSON.stringify({}) });
        showToast("已关闭：" + name, "info");
        await refresh();
      }catch(e){
        showToast("关闭失败：" + name + " - " + e.message, "danger");
      }
    }

    async function delSrv(name){
      if(!confirm(`确定删除服务器 ${name} 吗？（会先断开连接）`)) return;
      try{
        await api(`/servers/registry/${name}`, { method:"DELETE" });
        showToast("已删除：" + name, "warning");
        await refresh();
      }catch(e){
        showToast("删除失败：" + name + " - " + e.message, "danger");
      }
    }

    async function addServer(){
      const name = (document.getElementById("new_name").value || "").trim();
      const abs_path = (document.getElementById("new_path").value || "").trim();
      const filename = (document.getElementById("new_filename").value || "").trim();
      const description = (document.getElementById("new_desc").value || "").trim();
      const auto_start = document.getElementById("new_autostart").checked;
      const overwrite = document.getElementById("new_overwrite").checked;

      if(!name){ showToast("名称不能为空", "danger"); return; }
      if(!abs_path && !filename){ showToast("脚本路径或文件名至少填写一个", "danger"); return; }

      const payload = { name, description, auto_start, overwrite };
      if(abs_path) payload.abs_path = abs_path;
      if(filename) payload.filename = filename;

      try{
        await api("/servers/registry", { method:"POST", body: JSON.stringify(payload) });
        bootstrap.Modal.getOrCreateInstance(document.getElementById("addModal")).hide();

        document.getElementById("new_name").value="";
        document.getElementById("new_path").value="";
        document.getElementById("new_filename").value="";
        document.getElementById("new_desc").value="";
        document.getElementById("new_autostart").checked=false;
        document.getElementById("new_overwrite").checked=false;

        showToast("已新增：" + name, "success");
        await refresh();
      }catch(e){
        showToast("新增失败：" + e.message, "danger");
      }
    }

    async function openTools(name){
      currentToolsServer = name;
      await reloadTools();
      bootstrap.Modal.getOrCreateInstance(document.getElementById("toolsModal")).show();
    }

    async function reloadTools(){
      if(!currentToolsServer) return;
      const hint = document.getElementById("toolsHint");
      const body = document.getElementById("toolsBody");
      hint.textContent = `服务器：${currentToolsServer}`;
      body.innerHTML = `<div class="text-secondary small">加载中...</div>`;

      try{
        const data = await api(`/servers/${currentToolsServer}/tools`);
        const tools = data.tools || [];

        if(!tools.length){
          body.innerHTML = `<div class="text-secondary">该服务器没有暴露工具</div>`;
          return;
        }

        const rows = tools.map(t => {
          const schema = t.inputSchema
            ? `<pre class="bg-body-tertiary p-2 rounded small mono mb-0">${esc(JSON.stringify(t.inputSchema, null, 2))}</pre>`
            : `<span class="text-secondary small">无参数结构（schema）</span>`;
          return `
            <div class="card mb-2">
              <div class="card-body">
                <div class="fw-semibold">${esc(t.name)}</div>
                <div class="text-secondary small">${esc(t.description || "")}</div>
                <div class="mt-2">${schema}</div>
              </div>
            </div>
          `;
        }).join("");

        body.innerHTML = rows;
      }catch(e){
        body.innerHTML = `<div class="text-danger">加载失败：${esc(e.message)}</div>`;
      }
    }

    async function downloadConfig(){
      try{
        await api("/config/mcp/generate", { method:"POST" });
        window.open("/config/mcp/download", "_blank");
      }catch(e){
        showToast("导出失败：" + e.message, "danger");
      }
    }

    async function openLogs(refreshOnly=false){
      try{
        const data = await api("/logs?limit=80");
        document.getElementById("logsBody").textContent = JSON.stringify(data.logs || [], null, 2);
        if(!refreshOnly){
          bootstrap.Modal.getOrCreateInstance(document.getElementById("logsModal")).show();
        }
      }catch(e){
        showToast("读取日志失败：" + e.message, "danger");
      }
    }

    refresh();
  </script>
</body>
</html>
"""

@router.get("/ui", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(_HTML)

@router.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(_HTML)
