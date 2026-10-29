import { json, sha256, allowedOrigin } from '../../_lib/api-auth.js';
const H = { 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
function b64url(bytes) { let s=''; for (const b of bytes) s+=String.fromCharCode(b); return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/g,''); }
function fromB64url(value) { const s=value.replace(/-/g,'+').replace(/_/g,'/'); const raw=atob(s+'='.repeat((4-s.length%4)%4)); return Uint8Array.from(raw,c=>c.charCodeAt(0)); }
async function encryptionKey(secret) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret));
  return crypto.subtle.importKey('raw', digest, { name:'AES-GCM' }, false, ['encrypt','decrypt']);
}
async function encryptKey(secret, apiKey) {
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const cipher=await crypto.subtle.encrypt({name:'AES-GCM',iv},await encryptionKey(secret),new TextEncoder().encode(apiKey));
  return b64url(iv)+'.'+b64url(new Uint8Array(cipher));
}
async function decryptKey(secret, value) {
  const [iv,cipher]=String(value).split('.');
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:fromB64url(iv)},await encryptionKey(secret),fromB64url(cipher));
  return new TextDecoder().decode(plain);
}
export async function onRequestPost(context) {
  const origin=allowedOrigin(context.request,context.env);
  const cors=origin?{'Access-Control-Allow-Origin':origin,'Vary':'Origin'}:{};
  if(!origin)return json({error:'ORIGIN_NOT_ALLOWED'},403,{...H,...cors});
  if(!context.env.PAYSTACK_SECRET_KEY||!context.env.MATCH_SIGNAL_DB)return json({error:'PAYMENTS_NOT_CONFIGURED'},503,{...H,...cors});
  let body; try{body=await context.request.json()}catch{return json({error:'INVALID_JSON'},400,{...H,...cors})}
  const reference=String(body.reference||'').trim();
  const token=String(body.checkout_token||'');
  if(!/^MS_[A-Za-z0-9_-]{8,100}$/.test(reference)||token.length<32||token.length>100)return json({error:'INVALID_PAYMENT_REFERENCE'},400,{...H,...cors});
  try {
    const payment=await context.env.MATCH_SIGNAL_DB.prepare('SELECT * FROM ms_payments WHERE reference=? LIMIT 1').bind(reference).first();
    if(!payment||await sha256(token)!==payment.checkout_token_hash)return json({error:'PAYMENT_SESSION_INVALID'},403,{...H,...cors});
    const upstream=await fetch('https://api.paystack.co/transaction/verify/'+encodeURIComponent(reference),{headers:{Authorization:'Bearer '+context.env.PAYSTACK_SECRET_KEY}});
    const verified=await upstream.json();
    if(!upstream.ok||!verified.status||verified.data?.status!=='success'||verified.data?.reference!==reference||Number(verified.data?.amount)!==Number(payment.amount_kobo)||verified.data?.currency!=='NGN'||String(verified.data?.customer?.email||'').toLowerCase()!==payment.email)
      return json({error:'PAYMENT_NOT_CONFIRMED',message:'Paystack has not confirmed a matching successful payment. Do not retry payment unless your Paystack receipt says it failed.'},402,{...H,...cors});
    await context.env.MATCH_SIGNAL_DB.prepare("UPDATE ms_payments SET status='paid',paystack_transaction_id=?,paid_at=COALESCE(paid_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE reference=?").bind(String(verified.data.id),reference).run();
    let keyRow=await context.env.MATCH_SIGNAL_DB.prepare('SELECT id,key_ciphertext,expires_at FROM ms_api_keys WHERE payment_reference=? LIMIT 1').bind(reference).first();
    let apiKey;
    if(keyRow){apiKey=await decryptKey(context.env.PAYSTACK_SECRET_KEY,keyRow.key_ciphertext);}
    else {
      apiKey='ms_live_'+b64url(crypto.getRandomValues(new Uint8Array(32)));
      const keyId='key_'+crypto.randomUUID();
      const keyHash=await sha256(apiKey);
      const ciphertext=await encryptKey(context.env.PAYSTACK_SECRET_KEY,apiKey);
      await context.env.MATCH_SIGNAL_DB.prepare("INSERT INTO ms_api_keys (id,email,key_hash,key_ciphertext,plan_code,status,expires_at,payment_reference) VALUES (?,?,?,?,?,'active',datetime('now','+30 days'),?)").bind(keyId,payment.email,keyHash,ciphertext,payment.plan_code,reference).run();
      keyRow=await context.env.MATCH_SIGNAL_DB.prepare('SELECT id,key_ciphertext,expires_at FROM ms_api_keys WHERE payment_reference=? LIMIT 1').bind(reference).first();
      if(!keyRow)return json({error:'KEY_ISSUANCE_FAILED',message:'Payment is confirmed. Contact support with your payment reference.'},500,{...H,...cors});
    }
    return json({status:'paid',email:payment.email,plan:payment.plan_code,api_key:apiKey,expires_at:keyRow.expires_at,usage:'Save this key now. Use Authorization: Bearer <api_key> with the Match Signal API. Never publish the key.'},200,{...H,...cors});
  } catch {
    return json({error:'PAYMENT_VERIFICATION_UNAVAILABLE',message:'The verification service is temporarily unavailable. Keep your payment reference and retry verification.'},503,{...H,...cors});
  }
}
export function onRequestOptions(context) {
  const origin=allowedOrigin(context.request,context.env);
  return new Response(null,{status:204,headers:{...H,...(origin?{'Access-Control-Allow-Origin':origin,'Vary':'Origin'}:{}),'Access-Control-Allow-Methods':'POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type'}});
}
