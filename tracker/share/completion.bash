_tracker_complete() {
    local current="${COMP_WORDS[COMP_CWORD]}"

    mapfile -t COMPREPLY < <("${COMP_WORDS[0]}" completion words "${current}" 2>/dev/null)
}

complete -o default -F _tracker_complete tracker t
