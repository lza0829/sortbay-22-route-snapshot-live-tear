import React, { useState } from 'react'
import { api } from '../api'
import { emitDataChanged, useDataChanged } from '../refresh'

const surface_panel = true
export default function Bags() {
  const [bags, setBags] = useState([])
  const [chutes, setChutes] = useState([])
  const [scans, setScans] = useState([])
  const [chuteId, setChuteId] = useState('')
  const [bagId, setBagId] = useState('')
  const [scanId, setScanId] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    try {
      const [bagRows, chuteRows, scanRows] = await Promise.all([
        api('/封袋'),
        api('/口门'),
        api(`/扫描?${encodeURIComponent('状态')}=${encodeURIComponent('已路由')}`),
      ])
      setBags(bagRows)
      setChutes(chuteRows)
      setScans(scanRows)
      if (!chuteId && chuteRows[0]) setChuteId(String(chuteRows[0].id))
    } catch (e) {
      setErr(e.message)
    }
  }
  useDataChanged(load)

  const selectedBag = bags.find((b) => String(b.id) === String(bagId))
  const eligibleScans = selectedBag
    ? scans.filter((s) => s.chute_id === selectedBag.chute_id && s.口径一致 !== false)
    : scans

  const openBag = async () => {
    try {
      const b = await api('/封袋/开袋', { method: 'POST', body: JSON.stringify({ 口门编号: Number(chuteId) }) })
      setMsg(`已开袋 ${b.code}`)
      setBagId(String(b.id))
      setScanId('')
      await load()
      emitDataChanged({ type: 'bag-opened', id: b.id })
    } catch (e) { setErr(e.message) }
  }

  const add = async () => {
    setErr(''); setMsg('')
    try {
      const row = await api(`/封袋/${bagId}/入袋`, { method: 'POST', body: JSON.stringify({ 扫描编号: Number(scanId) }) })
      setMsg(`入袋成功：${row.barcode} 按实落口 ${row.实落口门码 || row.chute_id} 准入`)
      setScanId('')
      await load()
      emitDataChanged({ type: 'scan-bagged', id: row.id })
    } catch (e) { setErr(e.message) }
  }

  const seal = async () => {
    setErr(''); setMsg('')
    try {
      const bag = await api(`/封袋/${bagId}/封口`, { method: 'POST' })
      setMsg(`封袋成功：${bag.code}`)
      await load()
      emitDataChanged({ type: 'bag-sealed', id: bag.id })
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className={surface_panel ? "panel" : "panel"}>
      <h2>封袋 · 口门准入</h2>
      {msg && <div className="msg">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <div className="row">
        <label>口门
          <select value={chuteId} onChange={(e) => setChuteId(e.target.value)}>
            {chutes.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
          </select>
        </label>
        <button type="button" onClick={openBag}>开袋</button>
      </div>
      <div className="row">
        <label>袋编号<input value={bagId} onChange={(e) => { setBagId(e.target.value); setScanId('') }} /></label>
        <label>该袋准入的已路由扫描
          <select value={scanId} onChange={(e) => setScanId(e.target.value)}>
            <option value="">选择</option>
            {eligibleScans.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} · {s.barcode} · {s.实落口门码 || s.chute_id}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={add} disabled={!bagId || !scanId}>入袋</button>
        <button type="button" className="secondary" onClick={seal} disabled={!bagId}>封口</button>
      </div>
      {selectedBag && (
        <p className="muted">
          当前袋 {selectedBag.code} 对应口门 {selectedBag.口门码}；
          下拉仅显示实落口与袋口门一致的 {eligibleScans.length} 笔。错口请求由后端事务拒绝并写审计。
        </p>
      )}
      <table>
        <thead><tr><th>编号</th><th>袋码</th><th>口门</th><th>状态</th><th>件数</th></tr></thead>
        <tbody>
          {bags.map((b) => (
            <tr key={b.id} className={String(b.id) === String(bagId) ? 'selected-row' : ''}>
              <td>{b.id}</td>
              <td><button type="button" className="link" onClick={() => setBagId(String(b.id))}>{b.code}</button></td>
              <td>{b.口门码}</td><td>{b.status}</td><td>{b.件数}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
