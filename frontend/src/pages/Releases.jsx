import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { FrozenBadge, LockedButton, isFrozen } from '../components/FreezeBadge'

const surface_panel = true
export default function Releases() {
  const [rows, setRows] = useState([])
  const [apps, setApps] = useState([])
  const [appId, setAppId] = useState('')
  const [ver, setVer] = useState('')
  const [digest, setDigest] = useState('')
  const [onlyUnclosed, setOnlyUnclosed] = useState(false)
  const [onlyFrozen, setOnlyFrozen] = useState(false)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    const params = new URLSearchParams()
    if (onlyUnclosed) params.set('未收口', '1')
    if (onlyFrozen) params.set('冻结', '1')
    const qs = params.toString()
    setRows(await api('/发版单' + (qs ? `?${qs}` : '')))
    const a = await api('/应用')
    setApps(a)
    if (!appId && a[0]) setAppId(String(a[0].编号))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [onlyUnclosed, onlyFrozen])

  const create = async () => {
    setErr(''); setNotice('')
    try {
      await api('/发版单', {
        method: 'POST',
        body: JSON.stringify({ 应用编号: Number(appId), 目标版本: ver, 制品摘要: digest }),
      })
      setVer(''); setDigest(''); load()
    } catch (e) { setErr(e.message) }
  }
  const pipeline = async (id, status, row) => {
    setErr(''); setNotice('')
    try {
      await api(`/发版单/${id}/流水线`, { method: 'POST', body: JSON.stringify({ 流水线: status }) })
      load()
    } catch (e) {
      setErr(isFrozen(row) ? `写口已收口：${e.message}` : e.message)
      load()
    }
  }
  const admit = async (id, row) => {
    setErr(''); setNotice('')
    try {
      await api(`/发版单/${id}/入闸`, { method: 'POST', body: '{}' })
      load()
    } catch (e) {
      setErr(isFrozen(row) ? `入闸写口关闭（停用/冻结收口）：${e.message}` : e.message)
      load()
    }
  }

  const shown = onlyUnclosed ? rows.filter((r) => r.未收口) : rows

  return (
    <div className="panel">
      <h2>发版单 · 未收口列表 / 停用收口旁读</h2>
      {err && <p className="err" role="alert">{err}</p>}
      {notice && <p className="ok">{notice}</p>}
      <div className="row">
        <label>应用
          <select value={appId} onChange={(e) => setAppId(e.target.value)}>
            {apps.map((a) => <option key={a.编号} value={a.编号}>{a.名称}{a.状态 === '退役' ? '（退役冻结）' : a.状态 === '停用' ? '（停用收口）' : ''}</option>)}
          </select>
        </label>
        <label>目标版本<input value={ver} onChange={(e) => setVer(e.target.value)} placeholder="1.4.0" /></label>
        <label>制品摘要<input value={digest} onChange={(e) => setDigest(e.target.value)} placeholder="sha256:..." /></label>
        <button type="button" onClick={create}>申请入闸</button>
        <button
          type="button"
          className={onlyUnclosed ? '' : 'secondary'}
          aria-pressed={onlyUnclosed}
          onClick={() => setOnlyUnclosed((v) => !v)}
        >
          {onlyUnclosed ? '只看未收口 ✓' : '只看未收口发版单'}
        </button>
        <button
          type="button"
          className={onlyFrozen ? '' : 'secondary'}
          aria-pressed={onlyFrozen}
          data-testid="filter-frozen"
          onClick={() => setOnlyFrozen((v) => !v)}
        >
          {onlyFrozen ? '只看冻结/停用收口 ✓' : '只看冻结/停用收口'}
        </button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>收口态</th>
              <th>单态收口</th><th>冻结标</th><th>流水线</th><th>当前环境</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const frozen = isFrozen(r)
              return (
                <tr key={r.编号} className={frozen ? 'row-frozen' : ''} data-frozen={frozen ? '1' : '0'} data-app-status={r.应用状态}>
                  <td>{r.发版单号}</td>
                  <td>{r.应用}{r.应用状态 === '退役' ? <span className="muted">（退役）</span> : r.应用状态 === '停用' ? <span className="muted">（停用）</span> : null}</td>
                  <td>{r.目标版本}</td>
                  <td>{r.状态}</td>
                  <td data-field="收口态">{r.收口态}</td>
                  <td data-field="单态收口" data-same-core={r.同核收口 ? '1' : '0'}>{r.单态收口 || (r.同核收口 ? '已收口' : '未收口')}</td>
                  <td><FrozenBadge row={r} /></td>
                  <td>{r.流水线}</td>
                  <td>{r.当前环境 || '-'}</td>
                  <td className="action-cell">
                    <LockedButton
                      frozen={frozen}
                      mouth="流水线回执"
                      closed={r.写口?.流水线回执 === false}
                      data-open={r.写口?.流水线回执 ? '1' : '0'}
                      className="secondary"
                      onClick={() => pipeline(r.编号, '绿', r)}
                    >流水线绿</LockedButton>{' '}
                    <LockedButton
                      frozen={frozen}
                      mouth="流水线回执"
                      closed={r.写口?.流水线回执 === false}
                      data-open={r.写口?.流水线回执 ? '1' : '0'}
                      className="danger"
                      onClick={() => pipeline(r.编号, '红', r)}
                    >流水线红</LockedButton>{' '}
                    <LockedButton
                      frozen={frozen}
                      mouth="入闸"
                      closed={r.写口?.入闸 === false}
                      data-open={r.写口?.入闸 ? '1' : '0'}
                      onClick={() => admit(r.编号, r)}
                    >入闸</LockedButton>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
