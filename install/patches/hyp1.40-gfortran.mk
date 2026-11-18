# Makefile for HYPOINVERSE-2000 version 1.40 (Fred Klein, USGS) with gfortran.
#
# install/components/tools.sh copies this file over source/makefile of the USGS archive hyp1.40.tar.
# That makefile calls the old g77 compiler (no longer available), links with -Bstatic and copies the
# program into its author's own folder. The program and its object files are the same as there.
# -std=legacy lets today's gfortran accept the old Fortran 77 code (it prints warnings, no errors).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License (this file).

FC     = gfortran
FFLAGS = -O -std=legacy

OBJS = hyp.o hybda.o hycmd.o hysta.o hydel.o hyate.o hyfmc.o hycal.o hyxmc.o hycrh.o \
       hycrt.o hystl.o hyopen.o hyinit.o hyphs.o hysou.o hytrl.o hyloc.o hysol.o hysvd.o \
       hytra.o hytrh.o hytrt.o hymag.o hyrep.o hylst.o hysum.o hyinp.o hypro.o medwt.o \
       utmcal.o hydelt.o hyedit.o hytime.o hybeg.o hypref.o hymagp.o linv.o linvol.o \
       hyfile.o hylinv.o hylin.o hycre.o hytre.o trvcon.o hydatum.o allsubs.o

hyp1.40: $(OBJS)
	$(FC) $(FFLAGS) $(OBJS) -o $@

%.o: %.for
	$(FC) $(FFLAGS) -c $< -o $@

%.o: %.f
	$(FC) $(FFLAGS) -c $< -o $@

$(OBJS): $(wildcard *.inc)

clean:
	rm -f hyp1.40 *.o

.PHONY: clean
