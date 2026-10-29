import { json } from '../../_lib/api-auth.js';
const H = { 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
function hex(bytes){return [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('')}
async function signature(secret, raw){
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-512'},false,['sign']);
  return hex(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(raw)));
}
function constantTimeEqual(a,b){
  if(typeof a!=='string'||typeof b!=='string'||a.length!==b.length)return false;
  let diff=0;for(let i=0;i<a.length;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);return diff===0;
}
export async function onRequestPost(context){
  const secret=context.env.PAYSTACK_SECRET_KEY;
  if(!secret||!context.env.MATCH_SIGNAL_DB)return json({error:'PAYMENTS_NOT_CONFIGURED'},503,H);
  const raw=await context.request.text();
  const supplied=context.request.headers.get('x-paystack-signature')||'';
  const expected=await signature(secret,raw);
  if(!constantTimeEqual(supplied,expected))return json({error:'INVALID_SIGNATURE'},401,H);
  let event;try{event=JSON.parse(raw)}catch{return json({error:'INVALID_JSON'},400,H)}
  if(event.event!=='charge.success')return json({received:true},200,H);
  const data=event.data||{}, reference=String(data.reference||'');
  if(!reference)return json({received:true},200,H);
  try{
    const payment=await context.env.MATCH_SIGNAL_DB.prepare('SELECT email,amount_kobo,status FROM ms_payments WHERE reference=? LIMIT 1').bind(reference).first();
    if(!payment)return json({received:true},200,H);
    if(Number(data.amount)!==Number(payment.amount_kobo)||data.currency!=='NGN'||String(data.customer?.email||'').toLowerCase()!==payment.email)
      return json({error:'PAYMENT_DETAILS_MISMATCH'},400,H);
    await context.env.MATCH_SIGNAL_DB.prepare("UPDATE ms_payments SET status='paid',paystack_transaction_id=?,paid_at=COALESCE(paid_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE reference=? AND status IN ('initialized','paid')").bind(String(data.id||''),reference).run();
    return json({received:true},200,H);
  }catch{return json({error:'PAYMENT_LEDGER_UNAVAILABLE'},503,H)}
}
