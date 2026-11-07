"""
relay.py - Copies bytes between two sockets in both directions.

After a site is allowed, the client connects to the website and then simply
passes the bytes: browser -> website and website -> browser.
For HTTPS sites these bytes are encrypted between the browser and the website;
the client cannot read them and does not need to.
"""

import select

# Size of each piece we read from a socket.
BUFFER_SIZE = 65536


def relay(socket_a, socket_b, idle_timeout=60):
    """
    Pass data between socket_a and socket_b until one side closes the connection,
    or nothing happens for 'idle_timeout' seconds.
    """
    sockets = [socket_a, socket_b]

    while True:
        # select() waits until at least one of the sockets has data to read.
        readable, _, _ = select.select(sockets, [], [], idle_timeout)
        if len(readable) == 0:
            return  # Nothing happened for too long.

        for source in readable:
            # The data goes to the OTHER socket.
            if source is socket_a:
                destination = socket_b
            else:
                destination = socket_a

            try:
                data = source.recv(BUFFER_SIZE)
                if data == b"":
                    return  # This side closed the connection.
                destination.sendall(data)
            except OSError:
                return  # A network error: stop relaying.
