"""Recursos específicos de plataforma.

Submódulos têm dependências opcionais e **não** são importados pelo
``delfos`` por padrão. Em particular, ``delfos.platform.pi`` exige a
extra ``[pi]`` (``RPi.GPIO``) e só faz sentido em um Raspberry Pi.
"""
