import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { FrozenBadge, FateBanner, LockedButton, isFrozen } from '../components/FreezeBadge'

const surface_panel = true
export default function Promote() {
  const [rows, setRows] = useState([])
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setRows(active)
    if (!rid && active[0]) setRid(String(active[0].编号))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  const current = rows.find((r) => String(r.编号) === String(rid))
  const frozen = isFrozen(current)

  const go = async (target) => {
    setErr(''); setMsg('')
    const code = target || env
    try {
      const updated = await api(`/发版单/${rid}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: code }) })
      setMsg(`已晋升到 ${code}，当前状态 ${updated.状态}`)
      await load()
    } catch (e) {
      setErr(frozen ? `晋升/放行写口已关闭：${e.message}` : e.message)
      await load()
    }
  }

  const releaseToProd = async () => {
    setErr(''); setMsg('')
    try {
      const updated = await api(`/发版单/${rid}/放行`, { method: 'POST', body: JSON.stringify({}) })
      setMsg(`放行完成：${updated.发版单号} 已到产（${updated.状态}）`)
      await load()
    } catch (e) {
      setErr(`放行写口已关闭：${e.message}`)
      await load()
    }
  }

  return (
    <div className="panel">
      <h2>环境晋升 / 放行</h2>
      <p className="muted">晋升写口与放行写口是同一条发版管线命运：应用退役后，在途单冻结只读，晋升与放行一律驳回，环境链不再推进。</p>
      {err && <p className="err" role="alert">{err}</p>}
      {msg && <p className="ok" role="status">{msg}</p>}
      {frozen && <FateBanner row={current} />}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {rows.map((r) => (
              <option key={r.编号} value={r.编号}>
                {r.发版单号} · {r.应用}{isFrozen(r) ? ' · 已冻结' : ''} · {r.当前环境}
              </option>
            ))}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <LockedButton frozen={frozen} onClick={() => go()}>{frozen ? '晋升（已冻结·点按探针）' : '晋升'}</LockedButton>
        <LockedButton frozen={frozen} className="danger release-gate-btn" onClick={releaseToProd}>
          {frozen ? '放行到产（已关闭·点按探针）' : '放行到产'}
        </LockedButton>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>冻结标</th><th>读写态</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号} className={isFrozen(r) ? 'row-frozen' : ''}>
                <td>{r.发版单号}</td>
                <td>{r.应用}</td>
                <td>{r.目标版本}</td>
                <td>{r.状态}</td>
                <td>{r.当前环境}</td>
                <td><FrozenBadge row={r} /></td>
                <td>{r.读写态}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
