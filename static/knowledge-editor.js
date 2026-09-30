// Preserve evidence and metadata when a form edits only visible fields.
export function resolveParty(reference,parties){
  if(!reference)return null;
  const active=parties.filter(p=>p.status==='active');
  let matches=active.filter(p=>p.id===reference);
  if(!matches.length)matches=active.filter(p=>p.legal_identifier&&p.legal_identifier===reference);
  if(!matches.length)matches=active.filter(p=>p.name===reference||(p.aliases||[]).includes(reference));
  return {status:matches.length===1?'resolved':matches.length?'ambiguous':'not_found',
    id:matches.length===1?matches[0].id:null,reference};
}

export function knowledgeEditPayload(base,values){
  const metadata={...base.metadata};
  for(const key of ['counterparty_id','contract_type','project','department','decision_type','valid_from','valid_to']){
    if(Object.hasOwn(values,key)){
      if(values[key])metadata[key]=values[key];
      else metadata[key]=null;
    }
  }
  const sources=(base.sources||[]).flatMap((source,index)=>{
    if(values['remove_source_'+index])return [];
    const excerpt=values['source_excerpt_'+index]??source.excerpt;
    const copy={...source,excerpt};delete copy.source_available;
    return [copy];
  });
  for(const excerpt of (values.new_excerpts||'').split('\n').filter(line=>line.trim()))sources.push({excerpt});
  return {title:values.title,content:values.content,metadata,sources};
}
