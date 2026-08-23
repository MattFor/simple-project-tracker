function __tracker_candidates
    set -l binary (commandline -opc)[1]

    if test -z "$binary"
        set binary tracker
    end

    command $binary completion words (commandline -ct) 2>/dev/null
end

complete -c tracker -f -a "(__tracker_candidates)"
complete -c t -f -a "(__tracker_candidates)"
