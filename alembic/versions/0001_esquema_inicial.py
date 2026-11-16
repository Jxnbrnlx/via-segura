"""Esquema inicial de VÍA SEGURA

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BigPK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
GRAV = "('Con Muertos', 'Con Heridos', 'Solo Daños')"


def _pk(t):
    return sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}"))


def _fk(t, col, ref, ondelete=None):
    return sa.ForeignKeyConstraint([col], [f"{ref}.id"], name=op.f(f"fk_{t}_{col}_{ref}"), ondelete=ondelete)


def _ck(t, nombre, expr):
    return sa.CheckConstraint(expr, name=op.f(f"ck_{t}_{nombre}"))


def _tiempos():
    return [
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "fuentes_datos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(60), nullable=False),
        sa.Column("entidad", sa.String(150), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("url", sa.String(500)),
        sa.Column("fecha_publicacion", sa.Date()),
        sa.Column("fecha_descarga", sa.DateTime(timezone=True)),
        sa.Column("periodo_inicio", sa.Date()),
        sa.Column("periodo_fin", sa.Date()),
        sa.Column("formato", sa.String(30), nullable=False),
        sa.Column("prioridad", sa.SmallInteger(), server_default="100", nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notas", sa.Text()),
        *_tiempos(),
        _ck("fuentes_datos", "periodo", "periodo_fin IS NULL OR periodo_inicio IS NULL OR periodo_fin >= periodo_inicio"),
        _ck("fuentes_datos", "prioridad", "prioridad >= 1"),
        _pk("fuentes_datos"),
        sa.UniqueConstraint("codigo", name=op.f("uq_fuentes_datos_codigo")),
    )

    op.create_table(
        "usuarios_admin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("correo", sa.String(254), nullable=False),
        sa.Column("hash_contrasena", sa.String(255), nullable=False),
        sa.Column("rol", sa.String(20), server_default="admin", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(timezone=True)),
        _ck("usuarios_admin", "rol", "rol IN ('admin')"),
        _pk("usuarios_admin"),
        sa.UniqueConstraint("correo", name=op.f("uq_usuarios_admin_correo")),
    )

    op.create_table(
        "importaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fuente_id", sa.Integer()),
        sa.Column("usuario_id", sa.Integer()),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("modo", sa.String(20)),
        sa.Column("archivo", sa.String(255)),
        sa.Column("hoja", sa.String(120)),
        sa.Column("estado", sa.String(20), server_default="pendiente", nullable=False),
        sa.Column("iniciada_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finalizada_en", sa.DateTime(timezone=True)),
        sa.Column("filas_revisadas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_validas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_rechazadas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fecha_min_evento", sa.Date()),
        sa.Column("fecha_max_evento", sa.Date()),
        sa.Column("mapeo", sa.JSON()),
        sa.Column("errores", sa.JSON()),
        sa.Column("resumen", sa.JSON()),
        _ck("importaciones", "tipo", "tipo IN ('arcgis', 'excel')"),
        _ck("importaciones", "estado",
            "estado IN ('pendiente', 'previsualizada', 'en_proceso', 'completada', 'fallida', 'cancelada')"),
        _ck("importaciones", "conteos", "filas_revisadas >= 0 AND filas_validas >= 0 AND filas_rechazadas >= 0"),
        _fk("importaciones", "fuente_id", "fuentes_datos", "SET NULL"),
        _fk("importaciones", "usuario_id", "usuarios_admin", "SET NULL"),
        _pk("importaciones"),
    )
    op.create_index("ix_importaciones_iniciada_en", "importaciones", ["iniciada_en"])

    op.create_table(
        "siniestros_evento",
        sa.Column("id", BigPK, nullable=False),
        sa.Column("fuente_id", sa.Integer(), nullable=False),
        sa.Column("importacion_id", sa.Integer()),
        sa.Column("id_registro", sa.BigInteger(), nullable=False),
        sa.Column("formulario", sa.String(20)),
        sa.Column("fecha_evento", sa.Date(), nullable=False),
        sa.Column("anio", sa.SmallInteger(), nullable=False),
        sa.Column("mes", sa.SmallInteger()),
        sa.Column("dia_semana", sa.String(12)),
        sa.Column("hora", sa.SmallInteger()),
        sa.Column("minuto", sa.SmallInteger()),
        sa.Column("localidad", sa.String(60)),
        sa.Column("direccion", sa.String(150)),
        sa.Column("barrio", sa.String(255)),
        sa.Column("via_nombre", sa.String(255)),
        sa.Column("clase_siniestro", sa.String(40)),
        sa.Column("gravedad", sa.String(20)),
        sa.Column("gravedad_tradicional", sa.String(20)),
        sa.Column("latitud", sa.Float()),
        sa.Column("longitud", sa.Float()),
        sa.Column("coordenada_valida", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("motivo_coordenada", sa.String(20)),
        sa.Column("atributos", sa.JSON()),
        *_tiempos(),
        _ck("siniestros_evento", "mes", "mes IS NULL OR (mes BETWEEN 1 AND 12)"),
        _ck("siniestros_evento", "hora", "hora IS NULL OR (hora BETWEEN 0 AND 23)"),
        _ck("siniestros_evento", "minuto", "minuto IS NULL OR (minuto BETWEEN 0 AND 59)"),
        _ck("siniestros_evento", "lat_rango", "latitud IS NULL OR (latitud BETWEEN -90 AND 90)"),
        _ck("siniestros_evento", "lon_rango", "longitud IS NULL OR (longitud BETWEEN -180 AND 180)"),
        _ck("siniestros_evento", "gravedad", f"gravedad IS NULL OR gravedad IN {GRAV}"),
        _ck("siniestros_evento", "gravedad_trad", f"gravedad_tradicional IS NULL OR gravedad_tradicional IN {GRAV}"),
        _ck("siniestros_evento", "motivo_coord",
            "motivo_coordenada IS NULL OR motivo_coordenada IN "
            "('sin_coordenada', 'fuera_de_rango', 'fuera_de_bogota', 'sospechosa')"),
        _ck("siniestros_evento", "coord_coherente",
            "(coordenada_valida AND motivo_coordenada IS NULL) OR "
            "(NOT coordenada_valida AND motivo_coordenada IS NOT NULL)"),
        _ck("siniestros_evento", "coord_completa",
            "NOT coordenada_valida OR (latitud IS NOT NULL AND longitud IS NOT NULL)"),
        _fk("siniestros_evento", "fuente_id", "fuentes_datos", "RESTRICT"),
        _fk("siniestros_evento", "importacion_id", "importaciones", "SET NULL"),
        _pk("siniestros_evento"),
        sa.UniqueConstraint("fuente_id", "id_registro", name="uq_siniestros_evento_fuente_registro"),
    )
    op.create_index("ix_siniestros_fecha", "siniestros_evento", ["fecha_evento"])
    op.create_index("ix_siniestros_fuente_anio_loc", "siniestros_evento", ["fuente_id", "anio", "localidad"])
    op.create_index("ix_siniestros_gravedad", "siniestros_evento", ["gravedad"])
    op.create_index("ix_siniestros_clase", "siniestros_evento", ["clase_siniestro"])
    op.create_index("ix_siniestros_coord", "siniestros_evento", ["coordenada_valida", "latitud", "longitud"])

    op.create_table(
        "actores_viales",
        sa.Column("id", BigPK, nullable=False),
        sa.Column("siniestro_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        # Nulo permitido: en ArcGIS hay personas sin CODIGO_VEHICULO (verificado el 16-11-2026).
        sa.Column("codigo_vehiculo", sa.Integer(), nullable=True),
        sa.Column("consecutivo_victima", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(10)),
        sa.Column("condicion", sa.String(60)),
        sa.Column("condicion_especifica", sa.String(80)),
        sa.Column("sexo", sa.String(20)),
        sa.Column("edad", sa.SmallInteger()),
        sa.Column("rango_edad", sa.String(10)),
        sa.Column("muerte_posterior", sa.Boolean()),
        _ck("actores_viales", "estado", "estado IS NULL OR estado IN ('HERIDO', 'ILESO', 'MUERTO')"),
        _ck("actores_viales", "edad", "edad IS NULL OR (edad BETWEEN 0 AND 110)"),
        _fk("actores_viales", "siniestro_id", "siniestros_evento", "CASCADE"),
        _pk("actores_viales"),
        sa.UniqueConstraint("siniestro_id", "codigo_vehiculo", "consecutivo_victima",
                            name="uq_actores_viales_siniestro_vehiculo_victima"),
    )
    op.create_index("ix_actores_estado", "actores_viales", ["estado"])
    op.create_index("ix_actores_condicion", "actores_viales", ["condicion"])

    op.create_table(
        "vehiculos_evento",
        sa.Column("id", BigPK, nullable=False),
        sa.Column("siniestro_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("codigo_vehiculo", sa.Integer(), nullable=False),
        sa.Column("clase", sa.String(40)),
        sa.Column("servicio", sa.String(40)),
        sa.Column("modalidad", sa.String(60)),
        _fk("vehiculos_evento", "siniestro_id", "siniestros_evento", "CASCADE"),
        _pk("vehiculos_evento"),
        sa.UniqueConstraint("siniestro_id", "codigo_vehiculo", name="uq_vehiculos_evento_siniestro_vehiculo"),
    )
    op.create_index("ix_vehiculos_clase", "vehiculos_evento", ["clase"])

    op.create_table(
        "causas_evento",
        sa.Column("id", BigPK, nullable=False),
        sa.Column("siniestro_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("codigo_vehiculo", sa.Integer()),
        sa.Column("codigo_causa", sa.String(15), nullable=False),
        sa.Column("nombre", sa.String(80)),
        sa.Column("tipo_causa", sa.String(200)),
        _fk("causas_evento", "siniestro_id", "siniestros_evento", "CASCADE"),
        _pk("causas_evento"),
    )
    op.create_index("ix_causas_siniestro", "causas_evento", ["siniestro_id"])
    op.create_index("ix_causas_codigo", "causas_evento", ["codigo_causa"])

    op.create_table(
        "indicadores_agregados",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fuente_id", sa.Integer(), nullable=False),
        sa.Column("indicador", sa.String(80), nullable=False),
        sa.Column("unidad", sa.String(40), nullable=False),
        sa.Column("periodo_inicio", sa.Date()),
        sa.Column("periodo_fin", sa.Date()),
        sa.Column("localidad", sa.String(60)),
        sa.Column("categoria", sa.String(80)),
        sa.Column("valor", sa.Float(), nullable=False),
        sa.Column("notas", sa.Text()),
        _fk("indicadores_agregados", "fuente_id", "fuentes_datos", "RESTRICT"),
        _pk("indicadores_agregados"),
    )
    op.create_index("ix_indicadores_busqueda", "indicadores_agregados", ["fuente_id", "indicador", "periodo_inicio"])

    op.create_table(
        "denominadores_oficiales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fuente_id", sa.Integer(), nullable=False),
        sa.Column("localidad", sa.String(60), nullable=False),
        sa.Column("anio", sa.SmallInteger(), nullable=False),
        sa.Column("poblacion", sa.Integer(), nullable=False),
        _ck("denominadores_oficiales", "poblacion", "poblacion > 0"),
        _fk("denominadores_oficiales", "fuente_id", "fuentes_datos", "RESTRICT"),
        _pk("denominadores_oficiales"),
        sa.UniqueConstraint("fuente_id", "localidad", "anio", name="uq_denominadores_fuente_localidad_anio"),
    )


def downgrade() -> None:
    for tabla in (
        "denominadores_oficiales", "indicadores_agregados", "causas_evento", "vehiculos_evento",
        "actores_viales", "siniestros_evento", "importaciones", "usuarios_admin", "fuentes_datos",
    ):
        op.drop_table(tabla)
