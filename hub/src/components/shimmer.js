// Loading skeleton placeholders
export function shimmer(type = 'card', count = 3) {
  if (type === 'kpi') {
    return `<div class="shimmer-row">${Array.from({ length: 4 }, () => `
      <div class="shimmer-block shimmer-kpi">
        <div class="shimmer-line" style="width:60%;height:12px"></div>
        <div class="shimmer-line" style="width:40%;height:24px;margin-top:8px"></div>
        <div class="shimmer-line" style="width:100%;height:6px;margin-top:10px;border-radius:999px"></div>
      </div>
    `).join('')}</div>`;
  }

  if (type === 'table') {
    return `<div class="shimmer-block shimmer-table">
      <div class="shimmer-line" style="width:100%;height:36px;margin-bottom:2px"></div>
      ${Array.from({ length: 5 }, () => `<div class="shimmer-line" style="width:100%;height:36px;margin-bottom:2px"></div>`).join('')}
    </div>`;
  }

  return Array.from({ length: count }, () => `
    <div class="shimmer-block shimmer-card">
      <div style="display:flex;align-items:center;gap:12px">
        <div class="shimmer-circle" style="width:44px;height:44px"></div>
        <div style="flex:1">
          <div class="shimmer-line" style="width:65%;height:14px"></div>
          <div class="shimmer-line" style="width:40%;height:10px;margin-top:6px"></div>
        </div>
        <div class="shimmer-line" style="width:40px;height:20px"></div>
      </div>
      <div class="shimmer-line" style="width:100%;height:4px;margin-top:12px;border-radius:999px"></div>
    </div>
  `).join('');
}
