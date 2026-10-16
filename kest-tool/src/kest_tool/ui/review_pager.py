"""One review card at a time, retaining selection when saved items leave the list."""
import streamlit as st


def review_item(rows, *, key, identity, label):
    if not rows:
        return None
    selected_key = f'{key}_selected'
    index_key = f'{key}_index'
    selected = st.session_state.get(selected_key)
    index = next((i for i, r in enumerate(rows) if r[identity] == selected),
                 min(st.session_state.get(index_key, 0), len(rows)-1))
    def select(target):
        st.session_state[selected_key] = rows[target][identity]
        st.session_state[index_key] = target

    if len(rows) > 1:
        previous, counter, following = st.columns([1, 2, 1], vertical_alignment='center')
        previous.button('← Zurück', key=f'{key}_previous', disabled=index == 0,
                        on_click=select, args=(index-1,))
        following.button('Weiter →', key=f'{key}_next', disabled=index == len(rows)-1,
                         help='Änderungen vor dem Wechsel speichern.', on_click=select, args=(index+1,))
        counter.caption(f'{label} {index+1} von {len(rows)}')
    else:
        st.caption(f'{label} 1 von 1')
    st.session_state[selected_key] = rows[index][identity]
    st.session_state[index_key] = index
    return rows[index]
