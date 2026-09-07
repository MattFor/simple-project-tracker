_tracker() {
    local -a candidates

    candidates=("${(@f)$("${words[1]}" completion words "${words[CURRENT]}" 2>/dev/null)}")

    if ((${#candidates})); then
        compadd -- "${candidates[@]}"
    fi

    _files -/
}

compdef _tracker tracker t
