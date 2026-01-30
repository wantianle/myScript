(function() {
    let waypoints = [];
    let currentPreview = null;
    let isCollapsed = true;

    // ================= UI =================

    const panel = document.createElement('div');
    panel.id = 'coord-collector-panel';
    Object.assign(panel.style, {
        position: 'fixed',
        top: '10px',    // 靠顶
        left: '15px',   // 靠左
        zIndex: '10000',
        background: 'rgba(33, 37, 41, 0.95)',
        color: 'white',
        borderRadius: '50%',
        fontFamily: 'sans-serif',
        boxShadow: '0 4px 15px rgba(0,0,0,0.5)',
        width: '40px',       // 默认宽度
        height: '40px',      // 默认高度
        border: '1px solid #495057',
        userSelect: 'none',
        transition: 'width 0.2s, height 0.2s, border-radius 0.2s',
        overflow: 'hidden',
        touchAction: 'none'
    });

    panel.innerHTML = `
        <div id="collapsed-icon" style="display:flex; width:40px; height:40px; align-items:center; justify-content:center; cursor:pointer; font-size:20px;">📍</div>
        <div id="full-content" style="display:none; padding: 15px;">
            <div id="drag-handle" style="cursor: move; border-bottom: 1px solid #495057; padding-bottom: 8px; margin-bottom: 10px; font-weight: bold; display: flex; justify-content: space-between; align-items: center;">
                <span>📍 坐标采集器</span>
                <div style="display: flex; gap: 8px;">
                    <span id="collapse-btn" style="cursor: pointer; opacity: 0.7; font-size: 14px;">[折叠]</span>
                    <span id="close-panel-btn" style="cursor: pointer; font-size: 18px; opacity: 0.7;">×</span>
                </div>
            </div>
            <div id="preview-area" style="background: #1a1d20; padding: 8px; border-radius: 4px; margin-bottom: 10px; border: 1px dashed #6c757d;">
                <div style="font-size: 11px; color: #adb5bd; margin-bottom: 4px;">待确认坐标 (左键选取):</div>
                <div id="preview-coords" style="font-family: monospace; font-size: 12px; color: #0dcaf0; white-space: pre;">等待点击地图...</div>
            </div>
            <div style="margin-bottom: 10px;">
                <input type="text" id="point-comment" placeholder="输入点注释 (防止按键冲突)"
                       style="width: 100%; box-sizing: border-box; background: #343a40; border: 1px solid #6c757d; color: white; padding: 8px; border-radius: 4px; outline: none;">
            </div>
            <button id="confirm-btn" style="width: 100%; background: #0d6efd; color: white; border: none; padding: 8px; border-radius: 4px; cursor: pointer; font-weight: bold; margin-bottom: 10px;">确认记录 (Enter)</button>
            <div id="status-display" style="font-size: 12px; color: #ffc107; margin-bottom: 10px; display: flex; justify-content: space-between;">
                <span>已记录: 0 个点</span>
                <a href="#" id="view-all-btn" style="color: #0dcaf0; text-decoration: none;">[总览]</a>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
                <button id="undo-btn" style="background: #6c757d; color: white; border: none; padding: 6px; border-radius: 4px; cursor: pointer; font-size: 11px;">撤销</button>
                <button id="clear-btn" style="background: #dc3545; color: white; border: none; padding: 6px; border-radius: 4px; cursor: pointer; font-size: 11px;">清空</button>
            </div>
            <button id="download-btn" style="width: 100%; background: #28a745; color: white; border: none; padding: 8px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold;">下载文件</button>
        </div>
    `;
    document.body.appendChild(panel);

    const textareaField = document.getElementById('overview-edit-area') || (function(){
        // 动态确保遮罩层存在
        const ov = document.createElement('div');
        ov.id = 'coords-overlay';
        Object.assign(ov.style, {
            display: 'none', position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
            background: 'rgba(0,0,0,0.85)', zIndex: '10001', justifyContent: 'center', alignItems: 'center'
        });
        ov.innerHTML = `<div style="background: #212529; width: 85%; max-width: 700px; height: 80%; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; border: 1px solid #495057;">
            <div style="display: flex; justify-content: space-between; color: white; margin-bottom: 15px;"><h3>编辑器</h3><span id="close-overlay" style="cursor:pointer">×</span></div>
            <textarea id="overview-edit-area" spellcheck="false" style="flex: 1; background: #000; color: #2ecc71; padding: 15px; border-radius: 8px; font-family: monospace; border: 1px solid #333; outline: none; resize:none;"></textarea>
            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 15px;">
                <button id="save-overlay" style="background: #0d6efd; color: white; border: none; padding: 8px 20px; border-radius: 4px; cursor: pointer;">保存</button>
            </div>
        </div>`;
        document.body.appendChild(ov);
        return document.getElementById('overview-edit-area');
    })();

    const inputField = document.getElementById('point-comment');
    const collapsedIcon = document.getElementById('collapsed-icon');
    const fullContent = document.getElementById('full-content');

    // 防止 Dreamview 捕获逻辑 (回流)

    const preventCapture = (e) => {
        e.stopImmediatePropagation();
    };

    // 对输入框进行全按键拦截
    inputField.addEventListener('keydown', (e) => {
        e.stopImmediatePropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            confirmPoint();
        }
    }, true);
    inputField.addEventListener('keyup', preventCapture, true);
    inputField.addEventListener('keypress', preventCapture, true);

    // 屏蔽长拖拽误触发
    let isDragging = false;
    let startX, startY, xOffset = 0, yOffset = 0;
    let dragDistance = 0; // 记录拖拽位移

    function dragStart(e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;

        startX = e.clientX - xOffset;
        startY = e.clientY - yOffset;
        dragDistance = 0; // 重置位移

        if (e.target === collapsedIcon || document.getElementById('drag-handle').contains(e.target)) {
            isDragging = true;
        }
    }

    function drag(e) {
        if (isDragging) {
            e.preventDefault();
            let newX = e.clientX - startX;
            let newY = e.clientY - startY;

            // 计算累计位移
            dragDistance += Math.abs(newX - xOffset) + Math.abs(newY - yOffset);

            xOffset = newX;
            yOffset = newY;

            window.requestAnimationFrame(() => {
                panel.style.transform = `translate3d(${xOffset}px, ${yOffset}px, 0)`;
            });
        }
    }

    function dragEnd(e) {
        if (!isDragging) return;
        isDragging = false;

        if (dragDistance < 5) {
            if (e.target === collapsedIcon) toggleCollapse();
        }
    }

    panel.addEventListener('mousedown', dragStart);
    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', dragEnd);

    // ================= 功能函数 =================

    function toggleCollapse() {
        isCollapsed = !isCollapsed;
        if (isCollapsed) {
            panel.style.width = '40px';
            panel.style.height = '40px';
            panel.style.borderRadius = '50%';
            fullContent.style.display = 'none';
            collapsedIcon.style.display = 'flex';
        } else {
            panel.style.width = '260px';
            panel.style.height = 'auto';
            panel.style.borderRadius = '10px';
            fullContent.style.display = 'block';
            collapsedIcon.style.display = 'none';
            inputField.focus();
        }
    }

    function confirmPoint() {
        if (!currentPreview) return;
        waypoints.push({ ...currentPreview, comment: inputField.value.trim() || null });
        currentPreview = null;
        inputField.value = "";
        updateUI();
    }

    function updateUI() {
        panel.querySelector('#status-display span').innerText = `已记录: ${waypoints.length} 个点`;
        const previewEl = document.getElementById('preview-coords');
        if (!currentPreview) {
            previewEl.innerText = "等待点击地图...";
            previewEl.style.color = "#adb5bd";
        } else {
            previewEl.innerText = `X: ${currentPreview.x}\nY: ${currentPreview.y}`;
            previewEl.style.color = "#0dcaf0";
        }
    }

    // 地图点击逻辑
    window.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || panel.contains(e.target) || document.getElementById('coords-overlay').contains(e.target)) return;
        if (e.clientY < 120) return;

        const geoEl = document.querySelector('.geolocation');
        if (geoEl) {
            const matches = geoEl.innerText.match(/[-+]?[0-9]*\.?[0-9]+/g);
            if (matches && matches.length >= 2) {
                currentPreview = { x: matches[0], y: matches[1] };
                updateUI();
                if (!isCollapsed) inputField.focus();
            }
        }
    }, true);

    // 按钮绑定
    document.getElementById('collapse-btn').onclick = toggleCollapse;
    document.getElementById('confirm-btn').onclick = confirmPoint;
    document.getElementById('undo-btn').onclick = () => { waypoints.pop(); updateUI(); };
    document.getElementById('clear-btn').onclick = () => { if (confirm("清空？")) { waypoints = []; updateUI(); } };
    // 下载逻辑
    document.getElementById('download-btn').onclick = () => {
        if (waypoints.length === 0) return alert("记录为空");

        // 输入路线名称
        const routeName = prompt("请输入路线名称 (Landmark Name):", "未命名路线");

        if (routeName === null) return;

        // 格式化
        const waypointsContent = waypoints.map(p => {
            let block = "  waypoint {\n    pose {\n";
            block += `      x: ${p.x}\n`;
            block += `      y: ${p.y}\n`;
            block += `    }\n  }`;
            // 注释
            return p.comment ? `  # ${p.comment}\n${block}` : block;
        }).join("\n");

        // 包装 landmark 外层
        const finalFileContent = `landmark {\n  name: "${routeName}"\n${waypointsContent}\n}`;

        // 下载
        const blob = new Blob([finalFileContent], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${routeName}_${Date.now()}.txt`;
        a.click();
    };

    // 编辑器保存逻辑
    document.getElementById('view-all-btn').onclick = (e) => {
        e.preventDefault();
        const content = waypoints.map(p => `${p.comment ? '# '+p.comment+'\n':''}waypoint {\n  pose {\n    x: ${p.x}\n    y: ${p.y}\n  }\n}`).join("\n\n");
        textareaField.value = content;
        document.getElementById('coords-overlay').style.display = 'flex';
    };
    document.getElementById('save-overlay').onclick = () => {
        const text = textareaField.value;
        const newWaypoints = [];
        const regex = /(?:#\s*(.+?)\s*\n)?waypoint\s*{\s*pose\s*{\s*x:\s*([\d.]+)\s*y:\s*([\d.]+)\s*}\s*}/gs;
        let match;
        while ((match = regex.exec(text)) !== null) {
            newWaypoints.push({ comment: match[1] || null, x: match[2], y: match[3] });
        }
        waypoints = newWaypoints;
        updateUI();
        document.getElementById('coords-overlay').style.display = 'none';
    };
    document.getElementById('close-overlay').onclick = () => document.getElementById('coords-overlay').style.display = 'none';
    document.getElementById('close-panel-btn').onclick = () => { if (confirm("关闭？")) panel.remove(); };

})();
