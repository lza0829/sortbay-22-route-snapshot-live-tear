import React, { useState } from 'react'
import { api } from '../api'
import { useDataChanged } from '../refresh'

const surface_panel = true
export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/总览').then(setData).catch((e) => setErr(e.message))
  useDataChanged(load)

  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中…</div>
  const _ok = data && (data.surface_ok || data.surface_probe)
  const d = data.分布 || {}
  const _surf = _ok ? (data.surface_待路由 ?? d.待路由) : d.待路由
  const recon = data.路由对账 || {}
  return (
    <div className="panel">
      <h2>总览 · 已路由桶对账</h2>
      <p className="muted">
        当前班次：{data.班次?.business_day} {data.班次?.name} · {data.班次?.sealed ? '已封班' : '未封班'}
      </p>
      <p className={data.路由对齐 ? 'msg' : 'err'}>
        路由口径：{data.路由口径} · {data.路由对齐 ? '扫描册、裁决回执、口门、封袋准入与总览桶对齐' : `发现 ${recon.问题数 ?? 0} 处口径拧花，禁止亮已对齐`}
      </p>
      <div className="grid">
        {Object.entries(d).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
      </div>
      <p className="muted">
        已路由三方对读：总览桶 {data.总览已路由桶 ?? d.已路由} · 扫描册 {recon.扫描册已路由 ?? '-'} · 裁决回执 {recon.裁决回执已路由 ?? '-'}
      </p>
      <table>
        <thead><tr><th>口门</th><th>标题</th><th>状态</th><th>快照待裁</th><th>已路由桶</th><th>在口件数</th></tr></thead>
        <tbody>
          {(data.口门 || []).map((c) => (
            <tr key={c.id}>
              <td>{c.code}</td><td>{c.title}</td><td>{c.status}</td>
              <td>{c.快照待裁数 ?? 0}</td><td>{c.已路由数 ?? 0}</td><td>{c.在口件数}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!data.路由对齐 && (
        <table className="violations">
          <thead><tr><th>类型</th><th>扫描</th><th>拟落</th><th>实落</th><th>活表</th></tr></thead>
          <tbody>
            {(recon.问题 || []).map((v, i) => (
              <tr key={`${v.类型}-${v.scan_id || v.bag_id || v.rule_id || i}`} className="bad-row">
                <td>{v.类型}</td>
                <td>{v.scan_id || '-'}</td>
                <td>{v.拟落口门编号 ?? '-'}</td>
                <td>{v.实落口门编号 ?? v.scan_chute_id ?? '-'}</td>
                <td>{v.当前活表口门编号 ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
