// compact theme: the shared layout, styled by the tokens in theme.toml.
#import "../base.typ": resume
#resume(json(bytes(sys.inputs.data)))
