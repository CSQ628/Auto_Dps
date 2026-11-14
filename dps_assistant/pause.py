"""Persistent player intent and migration of proven legacy automatic pauses."""
import math

PAUSE_REASONS=frozenset(('global_paused','manual_instance_pause','protected_item_changed','legacy_instance_pause'))
PROTECTION_MESSAGE='旧版物品保护曾暂停此实例；正在自动恢复；新版异常仅记录警告。'


def pause_info(config,identity,state):
    if not config.get('running',True):return {'scope':'all','reason':'global_paused'}
    saved=state.get('pause',{})
    if not identity or config.get('instances',{}).get(identity,True) is not False:return None
    reason=saved.get('reason')
    if config.get('_instance_run_intent',{}).get(identity,{}).get('enabled') is False:reason='manual_instance_pause'
    if reason not in ('manual_instance_pause','protected_item_changed'):reason='legacy_instance_pause'
    result={'scope':'instance','reason':reason}
    at=saved.get('at')
    if type(at) in (int,float) and math.isfinite(at):result['at']=at
    if reason=='protected_item_changed':
        if type(saved.get('changed_count')) is int and saved['changed_count']>0:result['changed_count']=saved['changed_count']
        if saved.get('action_kind') in ('equipment','deposit','withdraw','sort','combine','decompose','forge','refine'):result['action_kind']=saved['action_kind']
    return result


def automatic_pause_evidence(config,states,events,modified):
    """Recover only proven automatic stops; never infer intent from an old diff alone."""
    recover={}
    intent=config.get('_instance_run_intent',{})
    latest={}
    for event in events:
        identity=event.get('identity')
        if identity and isinstance(event.get('action'),dict):latest[identity]=event
    for identity,enabled in config.get('instances',{}).items():
        if enabled is not False or identity in intent:continue
        reason=states.get(identity,{}).get('pause',{}).get('reason')
        if reason=='manual_instance_pause':continue
        if reason in ('protected_item_changed','tradable_state_changed'):
            recover[identity]='saved_automatic_pause';continue
        event=latest.get(identity,{})
        at=event.get('at');result=event.get('result') or {}
        # Old releases wrote the disabled config immediately BEFORE this receipt.
        # A later config write is ambiguous and must not override a player's choice.
        if type(at) in (int,float) and math.isfinite(at) and 0<=at-modified<=2 and result.get('protectedChanged'):
            recover[identity]='legacy_automatic_receipt'
    return recover
