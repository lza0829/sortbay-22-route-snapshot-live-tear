import React, { useState } from 'react'
import { api } from '../api'
import { emitDataChanged, useDataChanged } from '../refresh'

const surface_panel = true
export default function Scans() {
  const [rows, setRows] = useState([])
  const [barcode, setBarcode] = useState('')
  const [dest, setDest] = useState('110')
  const [msg, setMsg] = useState('')
  const [receipt, setReceipt] = useState(null)
  const [err, setErr] = useState('')

  const load = () => api('/扫描').then(setRows).catch((e) => setErr(e.message))
  useDataChanged(load)

  const create = async () => {
    setErr(''); setMsg(''); setReceipt(null)
    try {
      const row = await api('/扫描', { method: 'POST', body: JSON.stringify({ 条码: barcode, 目的地码: dest }) })
      setMsg('过机装载成功，已固化装载瞬间拟落口快照')
      setReceipt(row)
      setBarcode('')
      await load()
      emitDataChanged({ type: 'scan-created', id: row.id })
    } catch (e) { setErr(e.message) }
  }

  const routeOne = async (id) => {
    setErr(''); setMsg(''); setReceipt(null)
    try {
      const row = await api(`/扫描/${id}/路由`, { method: 'POST' })
      setReceipt(row)
      setMsg(`裁决成功：拟落 ${row.拟落口门码 || '-'}，实落 ${row.实落口门码 || '-'}，口径一致=${row.口径一致 ? '是' : '否'}`)
      await load()
      emitDataChanged({ type: 'scan-routed', id })
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className={surface_panel ? "panel" : "panel"}>
      <h2>过机扫描 · 装载快照口径</h2>
      <p className="muted">
        全局口径：装载时按当时路由表固化拟落口；路由表随后改档只显示为“当前活表”，不得回写本笔快照或改变裁决实落口。
      </p>
      <div className="row">
        <label>条码<input value={barcode} onChange={(e) => setBarcode(e.target.value)} /></label>
        <label>目的地码<input value={dest} onChange={(e) => setDest(e.target.value)} /></label>
        <button type="button" onClick={create}>装载扫描</button>
      </div>
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="err">{err}</div>}
      {receipt && (
        <pre className="receipt">裁决/装载回执：{JSON.stringify({
          id: receipt.id,
          status: receipt.status,
          拟落: receipt.拟落口门码,
          实落: receipt.实落口门码,
          当前活表: receipt.当前活表口门码,
          口径一致: receipt.口径一致,
        }, null, 2)}</pre>
      )}
      <table>
        <thead>
          <tr>
            <th>编号</th><th>条码</th><th>目的地</th><th>状态</th>
            <th>拟落口（装载快照）</th><th>实落/扫描口门</th><th>当前活表</th><th>对齐</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={r.口径一致 === false ? 'bad-row' : ''}>
              <td>{r.id}</td>
              <td>{r.barcode}</td>
              <td>{r.dest_code}</td>
              <td>{r.status}</td>
              <td>{r.拟落口门码 || r.planned_chute_id || '-'}</td>
              <td>{r.实落口门码 || r.chute_id || '-'}</td>
              <td>{r.当前活表口门码 || '-'}{r.路由表已改档 ? '（已改档，不回写）' : ''}</td>
              <td>{r.口径一致 ? '✓' : '拧花'}</td>
              <td>{(r.status === '待路由' || r.status === '错分回流') && <button type="button" onClick={() => routeOne(r.id)}>路由</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
