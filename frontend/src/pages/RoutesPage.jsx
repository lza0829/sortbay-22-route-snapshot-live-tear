import React, { useState } from 'react'
import { api } from '../api'
import { emitDataChanged, useDataChanged } from '../refresh'

const surface_panel = true
export default function RoutesPage() {
  const [rows, setRows] = useState([])
  const [chutes, setChutes] = useState([])
  const [policy, setPolicy] = useState(null)
  const [dest, setDest] = useState('')
  const [chuteId, setChuteId] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    try {
      const [routes, chuteRows, policyRow] = await Promise.all([
        api('/路由表'), api('/口门'), api('/路由口径'),
      ])
      setRows(routes)
      setChutes(chuteRows)
      setPolicy(policyRow)
      if (!chuteId && chuteRows[0]) setChuteId(String(chuteRows[0].id))
    } catch (e) { setErr(e.message) }
  }
  useDataChanged(load)

  const save = async () => {
    setErr(''); setMsg('')
    try {
      const row = await api('/路由表', { method: 'POST', body: JSON.stringify({ 目的地码: dest, 口门编号: Number(chuteId) }) })
      setMsg(`路由表已原子写入口门 ${row.口门码}，版本 v${row.version}；已有装载快照不回写`)
      setDest('')
      await load()
      emitDataChanged({ type: 'route-changed', id: row.id })
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className={surface_panel ? "panel" : "panel"}>
      <h2>路由表</h2>
      {policy && <p className="muted">当前全局口径：{policy.selected_policy}</p>}
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <div className="row">
        <label>目的地码<input value={dest} onChange={(e) => setDest(e.target.value)} /></label>
        <label>口门
          <select value={chuteId} onChange={(e) => setChuteId(e.target.value)}>
            {chutes.map((c) => <option key={c.id} value={c.id}>{c.code} {c.title}</option>)}
          </select>
        </label>
        <button type="button" onClick={save}>写入路由</button>
      </div>
      <table>
        <thead><tr><th>目的地码</th><th>当前口门</th><th>版本</th><th>备注</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td>{r.dest_code}</td><td>{r.口门码}</td><td>v{r.current_version || 1}</td><td>{r.note}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
